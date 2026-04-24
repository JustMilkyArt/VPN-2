"""
Server management service.
"""
import logging
import urllib.request
import json
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.server import Server, ServerStatus
from app.schemas.server import ServerCreate, ServerUpdate
from app.services.ssh_service import test_connection, get_server_info

logger = logging.getLogger(__name__)


def resolve_country(ip: str) -> str:
    """Определяет страну по IP через ipwho.is. Возвращает код страны или '??'."""
    try:
        url = f"https://ipwho.is/{ip}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("country_code"):
                return data["country_code"].upper()
    except Exception as e:
        logger.warning(f"Country resolve failed for {ip}: {e}")
    return "??"


def get_server(db: Session, server_id: int) -> Optional[Server]:
    return db.query(Server).filter(Server.id == server_id).first()


def get_servers(db: Session, skip: int = 0, limit: int = 100) -> List[Server]:
    return db.query(Server).offset(skip).limit(limit).all()


def create_server(db: Session, server_data: ServerCreate) -> Server:
    data = server_data.model_dump()
    # Если страна не передана или '??' — определяем по IP на бэкенде
    if not data.get("country") or data["country"] == "??":
        data["country"] = resolve_country(data["ip"])
    server = Server(**data)
    db.add(server)
    db.commit()
    db.refresh(server)
    logger.info(f"Created server {server.name} ({server.ip}), country={server.country}")
    return server


def update_server(db: Session, server: Server, update_data: ServerUpdate) -> Server:
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    db.commit()
    db.refresh(server)
    return server


def delete_server(db: Session, server: Server) -> None:
    db.delete(server)
    db.commit()


def check_server_status(db: Session, server: Server) -> ServerStatus:
    """Ping server via SSH and update status in DB."""
    ok, msg = test_connection(server)
    if ok:
        status = ServerStatus.ONLINE
    else:
        logger.warning(f"Server {server.ip} offline: {msg}")
        status = ServerStatus.OFFLINE
    
    server.status = status
    db.commit()
    db.refresh(server)
    return status


def get_server_details(server: Server) -> dict:
    """Get detailed server info via SSH."""
    info = get_server_info(server)
    return {
        "server_id": server.id,
        "name": server.name,
        "ip": server.ip,
        "status": server.status,
        "system_info": info
    }
