"""
Auth endpoints:
  POST /auth/login         — step 1: username + password → phase=totp + temp_token
  POST /auth/totp-verify   — step 2: temp_token + totp_code → full access_token
  GET  /auth/me            — current user profile
  POST /auth/change-creds  — self: change own username+password (requires TOTP)
"""
import logging
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.auth import (
    LoginRequest, LoginResponse, TotpVerifyRequest, TokenResponse,
    ChangeCredentialsRequest, ProfileResponse,
)
from app.models.admin_user import AdminUser
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user
from app.services.totp_service import verify_totp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory temp tokens: token → user_id (cleared after use or on restart)
_pending_totp: dict[str, int] = {}


def _issue_full_token(user: AdminUser) -> str:
    return create_access_token({"sub": user.username, "role": user.role.value})


# ─── Step 1: Login with username + password ───────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Step 1: Verify username + password.
    Returns phase='totp' with a short-lived temp_token to proceed to TOTP step.
    No TOTP code accepted here.
    """
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

    # Generate temp token for TOTP step
    temp_token = secrets.token_urlsafe(32)
    _pending_totp[temp_token] = user.id

    return LoginResponse(phase="totp", temp_token=temp_token)


# ─── Step 2: Verify TOTP code ─────────────────────────────────────────────────

@router.post("/totp-verify", response_model=TokenResponse)
def totp_verify(request: TotpVerifyRequest, db: Session = Depends(get_db)):
    """
    Step 2: Submit TOTP code with temp_token from step 1.
    Returns full access_token on success.
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

    # Consume temp token
    _pending_totp.pop(request.temp_token, None)

    # Mark totp_enabled + record last_login
    user.totp_enabled = True
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = _issue_full_token(user)
    return TokenResponse(access_token=token)


# ─── Profile ──────────────────────────────────────────────────────────────────

@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: AdminUser = Depends(get_current_user)):
    return current_user


# ─── Self: change own credentials (requires current TOTP) ────────────────────

@router.post("/change-creds", response_model=ProfileResponse)
def change_creds(
    req: ChangeCredentialsRequest,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    """
    User changes their own username + password.
    Always requires valid TOTP code.
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
    return current_user
