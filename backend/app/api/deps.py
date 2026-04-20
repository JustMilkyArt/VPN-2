from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.security import decode_access_token
from app.models.admin_user import AdminUser, UserRole
from app.models.session import ActiveSession, IDLE_TIMEOUT_SECONDS

security = HTTPBearer()

_IDLE_DELTA = timedelta(seconds=IDLE_TIMEOUT_SECONDS)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> AdminUser:
    """
    Authenticates the request:
    1. Decodes JWT (checks signature + exp)
    2. Looks up the server-side session by jti
    3. Checks idle timeout (last_activity + 10 min)
    4. Updates last_activity on every valid request
    5. Returns the AdminUser
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    _unauth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Сессия недействительна или истекла",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not payload:
        raise _unauth

    username = payload.get("sub")
    jti = payload.get("jti")

    if not username or not jti:
        raise _unauth

    # ── Server-side session check ──────────────────────────────────────────────
    sess: ActiveSession | None = db.get(ActiveSession, jti)

    if not sess:
        # Session was deleted (logout, idle timeout, or password change)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия завершена. Войдите снова.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Idle timeout check ────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)

    # last_activity may be timezone-naive if DB returns naive datetime
    last = sess.last_activity
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    if now - last > _IDLE_DELTA:
        # Idle timeout — delete session, respond 401
        db.delete(sess)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия завершена по истечении времени бездействия",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Update last_activity (sliding window) ─────────────────────────────────
    sess.last_activity = now
    db.commit()

    # ── Load user ─────────────────────────────────────────────────────────────
    user = db.query(AdminUser).filter(
        AdminUser.id == sess.user_id,
        AdminUser.is_active == True,
    ).first()

    if not user:
        db.delete(sess)
        db.commit()
        raise _unauth

    return user


# ─── Role-based dependencies ───────────────────────────────────────────────────

def require_role(*roles: UserRole):
    def _check(current_user: AdminUser = Depends(get_current_user)) -> AdminUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return _check


def require_creator():
    return require_role(UserRole.creator)


def require_head_admin_or_above():
    return require_role(UserRole.creator, UserRole.head_admin)


def require_any_admin():
    return require_role(UserRole.creator, UserRole.head_admin, UserRole.admin)


def can_manage_users(current_user: AdminUser = Depends(get_current_user)) -> AdminUser:
    if current_user.role not in (UserRole.creator, UserRole.head_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return current_user


def can_manage_target_user(target: AdminUser, actor: AdminUser):
    if target.role == UserRole.creator and actor.role != UserRole.creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify Creator account"
        )
    if target.role == UserRole.head_admin and actor.role == UserRole.head_admin and target.id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to modify this user"
        )
