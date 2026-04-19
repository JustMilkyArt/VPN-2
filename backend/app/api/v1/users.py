"""
Users management API (Creator and Главный админ only).

GET    /users/                    — list all users
POST   /users/                    — create user (returns one-time TOTP QR)
GET    /users/{id}                — get single user
PUT    /users/{id}                — update username / role / is_active
DELETE /users/{id}                — delete user
POST   /users/{id}/set-password   — reset another user's password (admin action)
POST   /users/{id}/toggle         — enable / disable
POST   /users/{id}/rebind-totp    — re-generate TOTP secret (returns new QR once)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.admin_user import AdminUser, UserRole
from app.schemas.auth import (
    AdminUserCreate, AdminUserRead,
    AdminUserCreateResponse, AdminUserUpdate,
    AdminUserSetPassword, RebindTotpResponse,
)
from app.core.security import get_password_hash
from app.api.deps import can_manage_users, can_manage_target_user
from app.services.totp_service import generate_totp_secret, generate_qr_base64

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


def _to_read(u: AdminUser) -> AdminUserRead:
    # Format date as DD.MM.YYYY
    if u.created_at:
        d = u.created_at
        created_str = f"{d.day:02d}.{d.month:02d}.{d.year}"
    else:
        created_str = None

    return AdminUserRead(
        id=u.id,
        username=u.username,
        role=u.role,
        is_active=u.is_active,
        totp_enabled=u.totp_enabled,
        created_by_id=u.created_by_id,
        created_at=created_str,
    )


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AdminUserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    q = db.query(AdminUser)
    # head_admin cannot see Creator
    if current_user.role == UserRole.head_admin:
        q = q.filter(AdminUser.role != UserRole.creator)
    users = q.order_by(AdminUser.created_at).all()
    return [_to_read(u) for u in users]


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=AdminUserCreateResponse, status_code=201)
def create_user(
    data: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    if data.role == UserRole.creator:
        raise HTTPException(status_code=403, detail="Нельзя создать ещё одного Creator")
    if data.role == UserRole.head_admin and current_user.role != UserRole.creator:
        raise HTTPException(status_code=403, detail="Только Creator может создать Главного Админа")

    if db.query(AdminUser).filter(AdminUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Логин уже занят")

    # TOTP secret generated immediately — admin hands QR to new user out-of-band
    secret = generate_totp_secret()
    user = AdminUser(
        username=data.username,
        password_hash=get_password_hash(data.password),
        role=data.role,
        totp_secret=secret,
        totp_enabled=True,          # active immediately — no separate confirmation needed
        created_by_id=current_user.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return AdminUserCreateResponse(
        user=_to_read(user),
        totp_qr=generate_qr_base64(secret, user.username),
        totp_secret=secret,
    )


# ─── Get single ───────────────────────────────────────────────────────────────

@router.get("/{user_id}", response_model=AdminUserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)
    return _to_read(user)


# ─── Update username / role / active ─────────────────────────────────────────

@router.put("/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)

    if data.username is not None:
        conflict = db.query(AdminUser).filter(
            AdminUser.username == data.username,
            AdminUser.id != user_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Логин уже занят")
        user.username = data.username

    if data.role is not None:
        if data.role == UserRole.creator:
            raise HTTPException(status_code=403, detail="Нельзя назначить роль Creator")
        if data.role == UserRole.head_admin and current_user.role != UserRole.creator:
            raise HTTPException(status_code=403, detail="Только Creator может назначить Главного Админа")
        user.role = data.role

    if data.is_active is not None:
        user.is_active = data.is_active

    db.commit()
    db.refresh(user)
    return _to_read(user)


# ─── Set password (admin resets another user's password) ─────────────────────

@router.post("/{user_id}/set-password", response_model=AdminUserRead)
def set_password(
    user_id: int,
    data: AdminUserSetPassword,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    """Admin resets password for a lower-role user (no TOTP required from admin side)."""
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)

    if not data.new_password or len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (минимум 6 символов)")

    user.password_hash = get_password_hash(data.new_password)
    db.commit()
    db.refresh(user)
    return _to_read(user)


# ─── Toggle enable/disable ────────────────────────────────────────────────────

@router.post("/{user_id}/toggle", response_model=AdminUserRead)
def toggle_user(
    user_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    """body: { "active": true/false }"""
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)
    user.is_active = bool(body.get("active", True))
    db.commit()
    db.refresh(user)
    return _to_read(user)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)
    db.delete(user)
    db.commit()


# ─── Rebind TOTP ──────────────────────────────────────────────────────────────

@router.post("/{user_id}/rebind-totp", response_model=RebindTotpResponse)
def rebind_totp(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    """
    Admin re-generates TOTP for a user. Old TOTP invalidated immediately.
    Returns new QR + secret ONCE — admin hands to user out-of-band.
    """
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    can_manage_target_user(user, current_user)

    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = True
    db.commit()

    return RebindTotpResponse(
        totp_qr=generate_qr_base64(secret, user.username),
        totp_secret=secret,
    )
