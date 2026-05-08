import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base


class UserRole(str, enum.Enum):
    creator = "creator"
    head_admin = "head_admin"
    admin = "admin"


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.admin, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # TOTP fields
    totp_secret = Column(String(64), nullable=True)   # base32 secret
    totp_enabled = Column(Boolean, default=False, nullable=False)

    # First login flow: require credentials change + TOTP setup
    force_change_creds = Column(Boolean, default=True, nullable=False)

    # Who created this user (NULL = system / self-created creator)
    created_by_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    created_by = relationship("AdminUser", remote_side=[id], foreign_keys=[created_by_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<AdminUser {self.username} [{self.role}]>"
