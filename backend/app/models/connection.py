from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.db.database import Base


class Protocol(str, enum.Enum):
    VLESS_REALITY = "vless_reality"
    TROJAN = "trojan"
    NAIVE_PROXY = "naive_proxy"


class ConnectionStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPLOYING = "deploying"
    ERROR = "error"


class Connection(Base):
    __tablename__ = "connections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    
    protocol = Column(String(30), nullable=False)
    port = Column(Integer, nullable=False)
    
    # Protocol-specific credentials (auto-generated)
    uuid = Column(String(36), nullable=True)         # For VLESS
    password = Column(String(255), nullable=True)    # For Trojan/NaiveProxy
    
    # Reality specific
    reality_public_key = Column(String(255), nullable=True)
    reality_private_key = Column(String(255), nullable=True)
    reality_short_id = Column(String(32), nullable=True)
    reality_server_name = Column(String(255), nullable=True, default="www.microsoft.com")
    
    # Full config JSON stored for client generation
    config_json = Column(Text, nullable=True)
    
    # Client connection string (vless:// or trojan:// URI)
    client_link = Column(Text, nullable=True)
    
    status = Column(String(20), nullable=False, default=ConnectionStatus.INACTIVE)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Target EU exit node (for chained connections)
    exit_server_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    server = relationship("Server", foreign_keys=[server_id], back_populates="connections")
    exit_server = relationship("Server", foreign_keys=[exit_server_id])

    def __repr__(self):
        return f"<Connection {self.name} [{self.protocol}] port={self.port} {self.status}>"
