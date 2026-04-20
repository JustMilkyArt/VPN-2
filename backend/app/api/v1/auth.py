"""
Auth endpoints:
  POST /auth/login         — step 1: username + password → phase=totp + temp_token
  POST /auth/totp-verify   — step 2: temp_token + totp_code → full access_token (creates session)
  POST /auth/logout        — invalidate current session immediately
  GET  /auth/me            — current user profile
  POST /auth/change-creds  — self: change own username+password (requires TOTP, invalidates all sessions)
"""
import logging
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _HAC
from sqlalchemy.orm import Session

_bearer = _HTTPBearer()

from app.db.database import get_db
from app.schemas.auth import (
    LoginRequest, LoginResponse, TotpVerifyRequest, TokenResponse,
    ChangeCredentialsRequest, ProfileResponse,
)
from app.models.admin_user import AdminUser
from app.core.security import (
    verify_password, get_password_hash, create_access_token,
    create_session, invalidate_session, invalidate_all_user_sessions,
)
from app.api.deps import get_current_user
from app.services.totp_service import verify_totp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory temp tokens: token → user_id (step 1 → step 2 handoff)
_pending_totp: dict[str, int] = {}


# ─── Step 1: username + password ──────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Step 1: verify username + password → returns temp_token for TOTP step."""
    user: AdminUser | None = db.query(AdminUser).filter(
        AdminUser.username == request.username,
        AdminUser.is_active == True,
    ).first()

    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин или пароль",
    )

    if not user or not verify_password(request.password, user.password_hash):
        raise auth_error

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аутентификатор не настроен. Обратитесь к администратору.",
        )

    temp_token = secrets.token_urlsafe(32)
    _pending_totp[temp_token] = user.id
    return LoginResponse(phase="totp", temp_token=temp_token)


# ─── Step 2: TOTP verify → issue full token + create server session ───────────

@router.post("/totp-verify", response_model=TokenResponse)
def totp_verify(request: TotpVerifyRequest, db: Session = Depends(get_db)):
    """
    Step 2: verify TOTP code with temp_token.
    On success: creates a server-side session record and returns JWT with jti.
    """
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный код аутентификатора",
    )

    user_id = _pending_totp.get(request.temp_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Войдите снова.",
        )

    user: AdminUser | None = db.query(AdminUser).filter(
        AdminUser.id == user_id,
        AdminUser.is_active == True,
    ).first()

    if not user or not user.totp_secret:
        _pending_totp.pop(request.temp_token, None)
        raise auth_error

    totp_code = (request.totp_code or "").strip()
    if not totp_code or not verify_totp(user.totp_secret, totp_code):
        raise auth_error

    # Consume temp token (one-time use)
    _pending_totp.pop(request.temp_token, None)

    # Record last_login
    user.totp_enabled = True
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    # Issue JWT with jti + create server-side session
    token, jti = create_access_token({"sub": user.username, "role": user.role.value})
    create_session(db, jti=jti, user_id=user.id)

    return TokenResponse(access_token=token)


# ─── Logout — invalidate session immediately ──────────────────────────────────

@router.post("/logout")
def logout(
    current_user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    credentials: _HAC = Depends(_bearer),
):
    """Delete the server-side session — JWT becomes immediately invalid."""
    from app.core.security import decode_access_token as _dec
    payload = _dec(credentials.credentials)
    if payload and payload.get("jti"):
        invalidate_session(db, payload["jti"])
    return {"detail": "Logged out"}


# ─── Profile ──────────────────────────────────────────────────────────────────

@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: AdminUser = Depends(get_current_user)):
    return current_user


# ─── Self: change own credentials ─────────────────────────────────────────────

@router.post("/change-creds", response_model=ProfileResponse)
def change_creds(
    req: ChangeCredentialsRequest,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Change own username + password. Requires valid TOTP.
    Invalidates ALL sessions for this user (security: forces re-login everywhere).
    """
    if not current_user.totp_secret or not verify_totp(current_user.totp_secret, req.totp_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный код аутентификатора",
        )

    if req.new_username != current_user.username:
        existing = db.query(AdminUser).filter(AdminUser.username == req.new_username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Логин уже занят")

    current_user.username = req.new_username
    current_user.password_hash = get_password_hash(req.new_password)
    db.commit()
    db.refresh(current_user)

    # Invalidate ALL sessions for security (including current one)
    invalidate_all_user_sessions(db, current_user.id)

    return current_user
