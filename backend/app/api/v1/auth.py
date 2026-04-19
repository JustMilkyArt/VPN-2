"""
Auth endpoints:
  POST /auth/login         — login: username + password + totp_code (always required)
  GET  /auth/me            — current user profile
  POST /auth/change-creds  — self: change own username+password (requires TOTP)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.auth import (
    LoginRequest, LoginResponse, TokenResponse,
    ChangeCredentialsRequest, ProfileResponse,
)
from app.models.admin_user import AdminUser
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user
from app.services.totp_service import verify_totp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_full_token(user: AdminUser) -> str:
    return create_access_token({"sub": user.username, "role": user.role.value})


# ─── Login ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Single-step login: username + password + totp_code always required.
    TOTP is set up by the admin before handing credentials to the user.
    Returns phase="ok" with full token on success.
    """
    user: AdminUser | None = db.query(AdminUser).filter(
        AdminUser.username == request.username,
        AdminUser.is_active == True,
    ).first()

    # Deliberate: same error for wrong user/password/totp to prevent enumeration
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин, пароль или код аутентификатора",
    )

    if not user or not verify_password(request.password, user.password_hash):
        raise auth_error

    # TOTP is mandatory for ALL users at ALL times
    if not user.totp_secret:
        # Account has no TOTP configured — block login, admin must set up via /users/{id}/rebind-totp
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аутентификатор не настроен. Обратитесь к администратору.",
        )

    totp_code = (request.totp_code or "").strip()
    if not totp_code:
        raise auth_error

    if not verify_totp(user.totp_secret, totp_code):
        raise auth_error

    # Mark totp as enabled if it was not yet (covers legacy accounts)
    if not user.totp_enabled:
        user.totp_enabled = True
        db.commit()

    token = _issue_full_token(user)
    return LoginResponse(phase="ok", access_token=token)


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
