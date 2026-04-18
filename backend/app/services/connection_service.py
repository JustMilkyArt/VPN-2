"""
Connection management service.
"""
import json
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.connection import Connection, Protocol, ConnectionStatus
from app.models.server import Server, ServerStatus
from app.schemas.connection import ConnectionCreate, ConnectionUpdate
from app.services.port_service import assign_free_port
from app.services.config_generator import generate_uuid, generate_password
from app.services import deploy_service

logger = logging.getLogger(__name__)


def get_connection(db: Session, connection_id: int) -> Optional[Connection]:
    return db.query(Connection).filter(Connection.id == connection_id).first()


def get_connections(db: Session, skip: int = 0, limit: int = 100) -> List[Connection]:
    return db.query(Connection).offset(skip).limit(limit).all()


def get_server_connections(db: Session, server_id: int) -> List[Connection]:
    return db.query(Connection).filter(Connection.server_id == server_id).all()


def create_connection(db: Session, conn_data: ConnectionCreate) -> Tuple[Connection, bool, str]:
    """
    Create a new connection:
    1. Assign free port
    2. Generate credentials
    3. Save to DB
    4. Deploy to server via SSH
    Returns: (connection, success, message)
    """
    # Get server
    server = db.query(Server).filter(Server.id == conn_data.server_id).first()
    if not server:
        return None, False, "Server not found"
    
    if not server.is_active:
        return None, False, "Server is disabled"

    # Assign port
    try:
        port = assign_free_port(db, conn_data.server_id, preferred_port=conn_data.port)
    except RuntimeError as e:
        return None, False, str(e)

    # Build connection object
    connection = Connection(
        name=conn_data.name,
        server_id=conn_data.server_id,
        protocol=conn_data.protocol,
        port=port,
        exit_server_id=conn_data.exit_server_id,
        notes=conn_data.notes,
        status=ConnectionStatus.DEPLOYING,
        reality_server_name=conn_data.reality_server_name or "www.microsoft.com"
    )

    # Generate credentials based on protocol
    if conn_data.protocol == Protocol.VLESS_REALITY:
        connection.uuid = generate_uuid()
    elif conn_data.protocol in (Protocol.TROJAN, Protocol.NAIVE_PROXY):
        connection.password = generate_password(32)

    db.add(connection)
    db.commit()
    db.refresh(connection)

    # Get exit server if specified
    exit_server = None
    if conn_data.exit_server_id:
        exit_server = db.query(Server).filter(Server.id == conn_data.exit_server_id).first()

    # Deploy to server
    ok, msg = _deploy_connection(db, connection, server, exit_server)

    if ok:
        connection.status = ConnectionStatus.ACTIVE
    else:
        connection.status = ConnectionStatus.ERROR
        logger.error(f"Deploy failed for connection {connection.id}: {msg}")

    db.commit()
    db.refresh(connection)
    return connection, ok, msg


def _deploy_connection(db: Session, connection: Connection, server: Server, exit_server: Optional[Server] = None) -> Tuple[bool, str]:
    """Dispatch deployment based on protocol."""
    if connection.protocol == Protocol.VLESS_REALITY:
        return deploy_service.deploy_vless_reality_connection(db, connection, server, exit_server)
    elif connection.protocol == Protocol.TROJAN:
        return deploy_service.deploy_trojan_connection(db, connection, server)
    elif connection.protocol == Protocol.NAIVE_PROXY:
        return deploy_service.deploy_naiveproxy_connection(db, connection, server)
    else:
        return False, f"Unknown protocol: {connection.protocol}"


def update_connection(db: Session, connection: Connection, update_data: ConnectionUpdate) -> Connection:
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(connection, field, value)
    db.commit()
    db.refresh(connection)
    return connection


def delete_connection(db: Session, connection: Connection) -> Tuple[bool, str]:
    """Remove connection from DB and from server config."""
    server = db.query(Server).filter(Server.id == connection.server_id).first()
    
    ok, msg = True, "Connection deleted (server offline)"
    if server and server.status == ServerStatus.ONLINE:
        ok, msg = deploy_service.delete_connection_from_server(db, connection, server)
    
    db.delete(connection)
    db.commit()
    return ok, msg


def toggle_connection(db: Session, connection: Connection, active: bool) -> Connection:
    connection.is_active = active
    connection.status = ConnectionStatus.ACTIVE if active else ConnectionStatus.INACTIVE
    db.commit()
    db.refresh(connection)
    return connection


def get_connections_grouped_by_server(db: Session) -> dict:
    """Return connections grouped by server for frontend display."""
    servers = db.query(Server).filter(Server.is_active == True).all()
    result = []
    
    for server in servers:
        conns = db.query(Connection).filter(Connection.server_id == server.id).all()
        result.append({
            "server": {
                "id": server.id,
                "name": server.name,
                "ip": server.ip,
                "country": server.country,
                "role": server.role,
                "status": server.status
            },
            "connections": [
                {
                    "id": c.id,
                    "name": c.name,
                    "protocol": c.protocol,
                    "port": c.port,
                    "status": c.status,
                    "client_link": c.client_link,
                    "is_active": c.is_active
                }
                for c in conns
            ]
        })
    
    return result
