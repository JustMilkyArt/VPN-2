from pydantic import BaseModel, field_validator
from typing import Optional
from app.models.admin_user import UserRole


# ─── Login ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str          # always required


class LoginResponse(BaseModel):
    phase: str              # always "ok" now
    access_token: str
    token_type: str = "bearer"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Profile / Change-creds ───────────────────────────────────────────────────

class ChangeCredentialsRequest(BaseModel):
    new_username: str
    new_password: str
    confirm_password: str
    totp_code: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Пароли не совпадают")
        return v


class ProfileResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    totp_enabled: bool

    class Config:
        from_attributes = True


# ─── User CRUD ────────────────────────────────────────────────────────────────

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


class AdminUserSetPassword(BaseModel):
    """Used by admin to reset another user's password."""
    new_password: str


class RebindTotpResponse(BaseModel):
    """Returned once when re-binding authenticator."""
    totp_qr: str
    totp_secret: str
