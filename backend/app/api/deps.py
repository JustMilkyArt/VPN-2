from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.security import decode_access_token
from app.models.admin_user import AdminUser, UserRole

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> AdminUser:
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(AdminUser).filter(
        AdminUser.username == username,
        AdminUser.is_active == True
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


# ─── Role-based dependencies ───────────────────────────────────────────────────

def require_role(*roles: UserRole):
    """Factory: returns a dependency that requires user to have one of the given roles."""
    def _check(current_user: AdminUser = Depends(get_current_user)) -> AdminUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return _check


def require_creator():
    """Only Creator."""
    return require_role(UserRole.creator)


def require_head_admin_or_above():
    """Creator or Главный админ."""
    return require_role(UserRole.creator, UserRole.head_admin)


def require_any_admin():
    """Any authenticated admin (all roles)."""
    return require_role(UserRole.creator, UserRole.head_admin, UserRole.admin)


def can_manage_users(current_user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """Creator and head_admin can manage users."""
    if current_user.role not in (UserRole.creator, UserRole.head_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return current_user


def can_manage_target_user(target: AdminUser, actor: AdminUser):
    """
    Enforce hierarchy rules on who can edit/delete whom.
    Raises HTTPException on violation.
    """
    # Nobody can edit Creator except Creator itself
    if target.role == UserRole.creator and actor.role != UserRole.creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify Creator account"
        )
    # head_admin cannot be deleted/modified by another head_admin
    if target.role == UserRole.head_admin and actor.role == UserRole.head_admin and target.id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to modify this user"
        )
