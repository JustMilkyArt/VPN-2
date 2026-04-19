from pydantic import BaseModel, field_validator
from typing import Optional
from app.models.admin_user import UserRole


# ─── Login ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None   # supplied when TOTP is already bound


class LoginResponse(BaseModel):
    """
    Two-phase login response.
    phase="ok"   → full token issued, user is in.
    phase="totp" → password correct but TOTP required; frontend must ask for code.
    phase="force_change" → first login, must change credentials + bind TOTP.
    """
    phase: str                          # "ok" | "totp" | "force_change"
    access_token: Optional[str] = None
    token_type: str = "bearer"
    # Returned only for phase=="force_change" so frontend can show TOTP setup
    totp_qr: Optional[str] = None      # base64 data URI
    totp_secret: Optional[str] = None  # raw base32 for manual entry


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Profile / Change-creds ───────────────────────────────────────────────────

class ChangeCredentialsRequest(BaseModel):
    new_username: str
    new_password: str
    confirm_password: str
    totp_code: str                      # always required when changing creds

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class ProfileResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    totp_enabled: bool
    force_change_creds: bool

    class Config:
        from_attributes = True


# ─── User CRUD (admin only) ───────────────────────────────────────────────────

class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.admin


class AdminUserRead(BaseModel):
    id: int
    username: str
    role: UserRole
    is_active: bool
    totp_enabled: bool
    force_change_creds: bool
    created_by_id: Optional[int] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserCreateResponse(BaseModel):
    """Returned once after user creation — contains one-time TOTP setup info."""
    user: AdminUserRead
    totp_qr: str        # base64 data URI — shown ONCE
    totp_secret: str    # raw base32 key — shown ONCE


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class RebindTotpResponse(BaseModel):
    """Returned once when re-binding authenticator."""
    totp_qr: str
    totp_secret: str
