"""
Users management API (visible only to Creator and Главный админ).

GET    /users/              — list all users (excl. Creator for head_admin)
POST   /users/              — create user (returns one-time TOTP QR)
GET    /users/{id}          — get single user
PUT    /users/{id}          — update role / active status / username
DELETE /users/{id}          — delete user
POST   /users/{id}/toggle   — enable/disable
POST   /users/{id}/rebind-totp — re-generate TOTP secret (returns new QR once)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.admin_user import AdminUser, UserRole
from app.schemas.auth import (
    AdminUserCreate, AdminUserRead,
    AdminUserCreateResponse, AdminUserUpdate, RebindTotpResponse,
)
from app.core.security import get_password_hash
from app.api.deps import can_manage_users, can_manage_target_user, get_current_user
from app.services.totp_service import generate_totp_secret, generate_qr_base64

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


def _to_read(u: AdminUser) -> AdminUserRead:
    return AdminUserRead(
        id=u.id,
        username=u.username,
        role=u.role,
        is_active=u.is_active,
        totp_enabled=u.totp_enabled,
        force_change_creds=u.force_change_creds,
        created_by_id=u.created_by_id,
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


@router.get("/", response_model=List[AdminUserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    q = db.query(AdminUser)
    # head_admin cannot see Creator account
    if current_user.role == UserRole.head_admin:
        q = q.filter(AdminUser.role != UserRole.creator)
    users = q.order_by(AdminUser.created_at).all()
    return [_to_read(u) for u in users]


@router.post("/", response_model=AdminUserCreateResponse, status_code=201)
def create_user(
    data: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    # Only Creator can create head_admin
    if data.role == UserRole.head_admin and current_user.role != UserRole.creator:
        raise HTTPException(status_code=403, detail="Only Creator can create Главный админ")
    # Nobody can create another Creator
    if data.role == UserRole.creator:
        raise HTTPException(status_code=403, detail="Cannot create another Creator")

    if db.query(AdminUser).filter(AdminUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    secret = generate_totp_secret()
    user = AdminUser(
        username=data.username,
        password_hash=get_password_hash(data.password),
        role=data.role,
        totp_secret=secret,
        totp_enabled=False,        # enabled after first confirm
        force_change_creds=True,   # must change on first login
        created_by_id=current_user.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return AdminUserCreateResponse(
        user=_to_read(user),
        totp_qr=generate_qr_base64(secret, user.username),
        totp_secret=secret,
    )


@router.get("/{user_id}", response_model=AdminUserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    can_manage_target_user(user, current_user)
    return _to_read(user)


@router.put("/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    can_manage_target_user(user, current_user)

    if data.username is not None:
        # Check uniqueness
        conflict = db.query(AdminUser).filter(
            AdminUser.username == data.username,
            AdminUser.id != user_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data.username

    if data.role is not None:
        # Cannot promote to creator
        if data.role == UserRole.creator:
            raise HTTPException(status_code=403, detail="Cannot promote to Creator")
        # Only creator can set head_admin
        if data.role == UserRole.head_admin and current_user.role != UserRole.creator:
            raise HTTPException(status_code=403, detail="Only Creator can assign Главный админ")
        user.role = data.role

    if data.is_active is not None:
        user.is_active = data.is_active

    db.commit()
    db.refresh(user)
    return _to_read(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    can_manage_target_user(user, current_user)
    db.delete(user)
    db.commit()


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
        raise HTTPException(status_code=404, detail="User not found")
    can_manage_target_user(user, current_user)
    user.is_active = bool(body.get("active", True))
    db.commit()
    db.refresh(user)
    return _to_read(user)


@router.post("/{user_id}/rebind-totp", response_model=RebindTotpResponse)
def rebind_totp(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(can_manage_users),
):
    """
    Re-generate TOTP secret for a user. Old TOTP is immediately invalidated.
    Returns new QR + secret ONCE.
    """
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    can_manage_target_user(user, current_user)

    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = False   # must be confirmed by the user on next login
    user.force_change_creds = True
    db.commit()
    return RebindTotpResponse(
        totp_qr=generate_qr_base64(secret, user.username),
        totp_secret=secret,
    )
