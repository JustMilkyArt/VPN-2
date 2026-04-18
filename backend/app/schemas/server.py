from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.server import ServerRole, ServerStatus


class ServerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    ip: str = Field(..., description="IP address or domain of the server")
    country: str = Field(default="??", max_length=10)
    role: ServerRole = ServerRole.EU
    ssh_user: str = Field(default="root", max_length=100)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    domain: Optional[str] = None
    notes: Optional[str] = None


class ServerCreate(ServerBase):
    ssh_key: Optional[str] = Field(None, description="Private SSH key (PEM format)")
    ssh_password: Optional[str] = Field(None, description="SSH password (if no key)")


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    role: Optional[ServerRole] = None
    ssh_user: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_key: Optional[str] = None
    ssh_password: Optional[str] = None
    domain: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ServerRead(ServerBase):
    id: int
    status: ServerStatus
    is_active: bool
    xray_installed: bool
    naiveproxy_installed: bool
    trojan_installed: bool
    warp_installed: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ServerStatusUpdate(BaseModel):
    is_active: bool


class ServerInstallRequest(BaseModel):
    install_xray: bool = True
    install_naiveproxy: bool = False
    install_trojan: bool = False
    install_warp: bool = False
