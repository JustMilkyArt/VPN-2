"""
Domain and Subdomain models for DNS management via Porkbun API.
"""
import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base


class DomainStatus(str, enum.Enum):
    pending = "pending"       # just added, not validated
    active = "active"         # API keys validated
    error = "error"           # validation failed


class SubdomainType(str, enum.Enum):
    admin_panel    = "admin_panel"
    client_site    = "client_site"
    vpn            = "vpn"
    none           = "none"
    swagger        = "swagger"
    naiveproxy_eu  = "naiveproxy_eu"
    naiveproxy_ru  = "naiveproxy_ru"


class SubdomainStatus(str, enum.Enum):
    pending = "pending"           # created, setup not started
    in_progress = "in_progress"   # setup running
    active = "active"             # fully configured + SSL
    error = "error"               # setup failed
    reserved = "reserved"         # VPN subdomain, A-record created later


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)   # e.g. milkyims.com

    # Porkbun API credentials
    porkbun_api_key = Column(String(255), nullable=False)
    porkbun_secret_key = Column(String(255), nullable=False)

    status = Column(Enum(DomainStatus), default=DomainStatus.pending, nullable=False)
    status_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    subdomains = relationship("Subdomain", back_populates="domain", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Domain {self.name} [{self.status}]>"


class Subdomain(Base):
    __tablename__ = "subdomains"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    domain = relationship("Domain", back_populates="subdomains")

    name = Column(String(100), nullable=False)          # e.g. "admin"
    full_name = Column(String(255), nullable=False)     # e.g. "admin.milkyims.com"

    subdomain_type = Column(Enum(SubdomainType), default=SubdomainType.none, nullable=False)

    # Target IP (auto-filled for admin_panel / client_site)
    target_ip = Column(String(100), nullable=True)

    # SSL info
    ssl_enabled = Column(Boolean, default=False, nullable=False)
    ssl_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Setup state
    nginx_configured = Column(Boolean, default=False, nullable=False)
    dns_record_created = Column(Boolean, default=False, nullable=False)

    status = Column(Enum(SubdomainStatus), default=SubdomainStatus.pending, nullable=False)
    status_message = Column(Text, nullable=True)

    # Step-by-step setup log (JSON array stored as text)
    setup_log = Column(Text, nullable=True)

    # Porkbun DNS record ID (to allow deletion)
    dns_record_id = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Subdomain {self.full_name} [{self.subdomain_type}] {self.status}>"
