"""
ActiveSession — server-side session store for idle-timeout enforcement.

Every successful login creates a record here.
Every authenticated request updates last_activity and checks for idle timeout.
Logout / idle-timeout deletes the record, making the JWT immediately invalid.
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


IDLE_TIMEOUT_SECONDS = 10 * 60   # 10 minutes — defined once, used by deps.py


class ActiveSession(Base):
    __tablename__ = "active_sessions"
    __table_args__ = {"extend_existing": True}

    # jti = JWT ID — unique per token, stored in JWT payload
    jti = Column(String(64), primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Updated on every authenticated request
    last_activity = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Hard expiry = login time + ACCESS_TOKEN_EXPIRE_MINUTES (safety net)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ActiveSession jti={self.jti[:8]}... user_id={self.user_id}>"
