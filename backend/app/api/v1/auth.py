"""
Auth endpoints:
  POST /auth/login            — step-1 (password) + step-2 (TOTP if bound)
  POST /auth/totp-verify      — step-2 when phase="totp" returned from login
  GET  /auth/me               — current user profile
  POST /auth/change-creds     — change username+password (always requires TOTP)
  POST /auth/bind-totp        — generate and bind TOTP for current user (one-time show)
  POST /auth/confirm-totp     — confirm TOTP setup with first code
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.auth import (
    LoginRequest, LoginResponse, TokenResponse,
    ChangeCredentialsRequest, ProfileResponse,
    RebindTotpResponse,
)
from app.models.admin_user import AdminUser
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user
from app.services.totp_service import (
    generate_totp_secret, generate_qr_base64, verify_totp
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Intermediate session store: maps temp_token → user_id
# In MVP we use a simple in-memory dict (single-process, sufficient for MVP)
_pending_totp: dict[str, int] = {}  # temp_token → user_id


def _issue_full_token(user: AdminUser) -> str:
    return create_access_token({"sub": user.username, "role": user.role.value})


# ─── Login (phase 1 / 2) ──────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user: AdminUser | None = db.query(AdminUser).filter(
        AdminUser.username == request.username,
        AdminUser.is_active == True,
    ).first()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # First login: must change credentials + setup TOTP
    if user.force_change_creds:
        # Generate TOTP secret (not yet bound — user must confirm)
        secret = generate_totp_secret()
        user.totp_secret = secret
        # Do NOT set totp_enabled yet — only after confirmation
        db.commit()
        temp_token = create_access_token({"sub": user.username, "phase": "force_change"}, )
        return LoginResponse(
            phase="force_change",
            access_token=temp_token,
            totp_qr=generate_qr_base64(secret, user.username),
            totp_secret=secret,
        )

    # TOTP enabled — require code
    if user.totp_enabled:
        if request.totp_code:
            # Code supplied inline (frontend provided both password + code)
            if not verify_totp(user.totp_secret, request.totp_code):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid TOTP code",
                )
            token = _issue_full_token(user)
            return LoginResponse(phase="ok", access_token=token)
        else:
            # Code not supplied — ask frontend to show TOTP step
            temp_token = create_access_token({"sub": user.username, "phase": "totp"})
            _pending_totp[temp_token] = user.id
            return LoginResponse(phase="totp", access_token=temp_token)

    # No TOTP — issue full token directly
    token = _issue_full_token(user)
    return LoginResponse(phase="ok", access_token=token)


@router.post("/totp-verify", response_model=TokenResponse)
def totp_verify(
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Verify TOTP code after phase="totp" response.
    Expects: { "temp_token": "...", "totp_code": "123456" }
    """
    temp_token = body.get("temp_token", "")
    totp_code = body.get("totp_code", "")

    from app.core.security import decode_access_token
    payload = decode_access_token(temp_token)
    if not payload or payload.get("phase") != "totp":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    user: AdminUser | None = db.query(AdminUser).filter(
        AdminUser.username == payload["sub"],
        AdminUser.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not verify_totp(user.totp_secret, totp_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    _pending_totp.pop(temp_token, None)
    token = _issue_full_token(user)
    return TokenResponse(access_token=token)


# ─── Profile ──────────────────────────────────────────────────────────────────

@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: AdminUser = Depends(get_current_user)):
    return current_user


# ─── Change credentials (requires TOTP always) ────────────────────────────────

@router.post("/change-creds", response_model=ProfileResponse)
def change_creds(
    req: ChangeCredentialsRequest,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Change username + password. TOTP code is always required.
    If this is first-login flow, also activates TOTP (marks totp_enabled=True).
    """
    # TOTP check
    if not current_user.totp_secret or not verify_totp(current_user.totp_secret, req.totp_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    # Check username uniqueness (if changed)
    if req.new_username != current_user.username:
        existing = db.query(AdminUser).filter(AdminUser.username == req.new_username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

    current_user.username = req.new_username
    current_user.password_hash = get_password_hash(req.new_password)
    current_user.totp_enabled = True
    current_user.force_change_creds = False
    db.commit()
    db.refresh(current_user)
    return current_user


# ─── Bind TOTP (generate new secret, show QR once) ───────────────────────────

@router.post("/bind-totp", response_model=RebindTotpResponse)
def bind_totp(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Generate a new TOTP secret and return QR + raw key ONCE.
    Does NOT immediately enable TOTP — user must call /confirm-totp.
    Previous TOTP is invalidated immediately (secret replaced).
    """
    secret = generate_totp_secret()
    current_user.totp_secret = secret
    current_user.totp_enabled = False   # disabled until confirmed
    db.commit()
    return RebindTotpResponse(
        totp_qr=generate_qr_base64(secret, current_user.username),
        totp_secret=secret,
    )


@router.post("/confirm-totp", response_model=ProfileResponse)
def confirm_totp(
    body: dict,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Confirm TOTP binding with first valid code.
    Expects: { "totp_code": "123456" }
    """
    code = body.get("totp_code", "")
    if not current_user.totp_secret or not verify_totp(current_user.totp_secret, code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")
    current_user.totp_enabled = True
    current_user.force_change_creds = False
    db.commit()
    db.refresh(current_user)
    return current_user
