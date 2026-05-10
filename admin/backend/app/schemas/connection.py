from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.connection import Protocol, ConnectionStatus


class ConnectionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    server_id: int
    protocol: Protocol
    exit_server_id: Optional[int] = None
    notes: Optional[str] = None


class ConnectionCreate(ConnectionBase):
    # Port is auto-assigned, but can be overridden
    port: Optional[int] = Field(None, ge=1024, le=65535)
    # Reality SNI override
    reality_server_name: Optional[str] = "www.microsoft.com"


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    exit_server_id: Optional[int] = None
    notes: Optional[str] = None


class ConnectionRead(ConnectionBase):
    id: int
    port: int
    uuid: Optional[str] = None
    password: Optional[str] = None
    reality_public_key: Optional[str] = None
    reality_private_key: Optional[str] = None
    reality_short_id: Optional[str] = None
    reality_server_name: Optional[str] = None
    # AmneziaWG
    wg_public_key: Optional[str] = None
    wg_client_private_key: Optional[str] = None
    wg_client_public_key: Optional[str] = None
    wg_preshared_key: Optional[str] = None
    wg_client_ip: Optional[str] = None
    awg_junk_packet_count: Optional[int] = None
    awg_junk_packet_min_size: Optional[int] = None
    awg_junk_packet_max_size: Optional[int] = None
    config_json: Optional[str] = None
    client_link: Optional[str] = None
    status: ConnectionStatus
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConnectionWithServer(ConnectionRead):
    server_name: Optional[str] = None
    server_ip: Optional[str] = None
    server_country: Optional[str] = None
    exit_server_name: Optional[str] = None
    exit_server_ip: Optional[str] = None
