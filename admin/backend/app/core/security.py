import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> tuple[str, str]:
    """
    Returns (token, jti).
    Every token gets a unique jti (JWT ID) so it can be individually invalidated.
    """
    to_encode = data.copy()
    jti = secrets.token_urlsafe(32)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "jti": jti})
    token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


# ─── Session store helpers ────────────────────────────────────────────────────

def create_session(db: Session, jti: str, user_id: int) -> None:
    """Create a server-side session record on login."""
    from app.models.session import ActiveSession
    # Remove any stale sessions for this user (optional: allow multi-session by removing this)
    # We keep multi-session: do NOT delete old sessions here.
    session = ActiveSession(
        jti=jti,
        user_id=user_id,
        last_activity=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()


def invalidate_session(db: Session, jti: str) -> None:
    """Delete a session record — makes the JWT immediately invalid."""
    from app.models.session import ActiveSession
    sess = db.get(ActiveSession, jti)
    if sess:
        db.delete(sess)
        db.commit()


def invalidate_all_user_sessions(db: Session, user_id: int) -> None:
    """Delete all sessions for a user (e.g. on password change)."""
    from app.models.session import ActiveSession
    db.query(ActiveSession).filter(ActiveSession.user_id == user_id).delete()
    db.commit()
