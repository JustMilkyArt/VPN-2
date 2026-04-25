from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
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


class SetupStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS  = "in_progress"
    DONE         = "done"
    FAILED       = "failed"


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
    ssh_key = Column(Text, nullable=True)           # private key (PEM) — для входа из панели
    ssh_private_key = Column(Text, nullable=True)   # авто-сгенерированный ключ (шаг 3)
    ssh_password = Column(String(255), nullable=True)  # аварийный пароль (для консоли провайдера)

    status = Column(String(20), nullable=False, default=ServerStatus.UNKNOWN)
    setup_status = Column(String(20), nullable=False, default=SetupStatus.NOT_STARTED)
    is_active = Column(Boolean, nullable=False, default=True)

    xray_installed = Column(Boolean, default=False)
    naiveproxy_installed = Column(Boolean, default=False)
    trojan_installed = Column(Boolean, default=False)
    awg_installed = Column(Boolean, default=False)
    warp_installed = Column(Boolean, default=False)

    # Для RU-серверов: привязанный EU-сервер (exit node)
    eu_server_id = Column(Integer, ForeignKey("servers.id", use_alter=True), nullable=True)

    domain = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    connections = relationship("Connection", back_populates="server", cascade="all, delete-orphan",
                               foreign_keys="Connection.server_id")

    # Привязанный EU-сервер (для RU) — self-referential
    eu_server = relationship(
        "Server",
        foreign_keys="[Server.eu_server_id]",
        primaryjoin="Server.eu_server_id == Server.id",
        remote_side="[Server.id]",
        uselist=False,
    )

    def __repr__(self):
        return f"<Server {self.name} ({self.ip}) [{self.role}] {self.status}>"
