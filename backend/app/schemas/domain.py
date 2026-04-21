"""
Pydantic schemas for Domain and Subdomain API.
"""
from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime


# ── Domain ────────────────────────────────────────────────────────────────────

class DomainCreate(BaseModel):
    name: str                    # e.g. "milkyims.com"
    porkbun_api_key: str
    porkbun_secret_key: str


class DomainRead(BaseModel):
    id: int
    name: str
    status: str
    status_message: Optional[str] = None
    created_at: Optional[datetime] = None
    subdomains: List["SubdomainRead"] = []

    class Config:
        from_attributes = True


# ── Subdomain ─────────────────────────────────────────────────────────────────

class SubdomainCreate(BaseModel):
    name: str                          # e.g. "admin"
    subdomain_type: str                # admin_panel | client_site | vpn | none
    target_ip: Optional[str] = None   # auto-filled if not provided


class SubdomainRead(BaseModel):
    id: int
    domain_id: int
    name: str
    full_name: str
    subdomain_type: str
    target_ip: Optional[str] = None
    ssl_enabled: bool
    ssl_expires_at: Optional[datetime] = None
    nginx_configured: bool
    dns_record_created: bool
    status: str
    status_message: Optional[str] = None
    setup_log: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


DomainRead.model_rebuild()


class SubdomainStatusRead(BaseModel):
    id: int
    status: str
    status_message: Optional[str] = None
    setup_log: Optional[str] = None

    class Config:
        from_attributes = True
