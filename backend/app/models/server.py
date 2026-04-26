from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.db.database import Base


class ServerRole(str, enum.Enum):
    RU = "RU"
    EU = "EU"


class ServerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    DEPLOYING = "deploying"
    SETTING_UP = "setting_up"
    NOT_CONFIGURED = "not_configured"


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip = Column(String(100), nullable=False, unique=True)
    country = Column(String(10), nullable=False, default="??")
    role = Column(String(10), nullable=False, default=ServerRole.EU)

    ssh_user = Column(String(100), nullable=False, default="root")
    ssh_port = Column(Integer, nullable=False, default=22)
    ssh_key = Column(Text, nullable=True)
    ssh_password = Column(String(255), nullable=True)

    status = Column(String(20), nullable=False, default=ServerStatus.UNKNOWN)
    is_active = Column(Boolean, nullable=False, default=True)

    xray_installed = Column(Boolean, default=False)
    naiveproxy_installed = Column(Boolean, default=False)
    awg_installed = Column(Boolean, default=False)
    warp_installed = Column(Boolean, default=False)

    domain = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    # ── Setup flow ──────────────────────────────────────────────────
    setup_status = Column(String(20), nullable=True)   # pending|in_progress|done|failed
    setup_step   = Column(String(50), nullable=True)   # step1..step5
    setup_error  = Column(Text, nullable=True)
    setup_log    = Column(Text, nullable=True)

    # ── Server info (собирается после setup) ───────────────────────
    server_timezone        = Column(String(100), nullable=True)
    xray_version           = Column(String(50),  nullable=True)
    caddy_version          = Column(String(50),  nullable=True)
    awg_version            = Column(String(50),  nullable=True)
    warp_version           = Column(String(50),  nullable=True)
    xray_public_key        = Column(Text, nullable=True)
    awg_server_public_key  = Column(Text, nullable=True)

    # ── Зашифрованные credentials (флаги для фронта) ───────────────
    ssh_private_key_enc = Column(Text, nullable=True)   # зашифрованный приватный ключ
    ssh_password_enc    = Column(Text, nullable=True)   # зашифрованный пароль

    # ── Актуальные SSH-параметры после харденинга ──────────────────
    ssh_user_actual = Column(String(100), nullable=True)
    ssh_port_actual = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    connections = relationship("Connection", back_populates="server", cascade="all, delete-orphan",
                               foreign_keys="Connection.server_id")

    def __repr__(self):
        return f"<Server {self.name} ({self.ip}) [{self.role}] {self.status}>"
