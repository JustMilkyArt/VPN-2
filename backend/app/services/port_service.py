"""
Port management service - auto-assigns free ports and checks conflicts.
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.connection import Connection

logger = logging.getLogger(__name__)


def get_used_ports(db: Session, server_id: int) -> List[int]:
    """Get all ports currently used on a server."""
    connections = db.query(Connection).filter(
        Connection.server_id == server_id,
        Connection.is_active == True
    ).all()
    return [c.port for c in connections]


def assign_free_port(
    db: Session,
    server_id: int,
    preferred_port: Optional[int] = None,
    start: int = None,
    end: int = None
) -> int:
    """
    Assign a free port for a new connection.
    Checks DB for conflicts. Returns the port number.
    """
    start = start or settings.PORT_RANGE_START
    end = end or settings.PORT_RANGE_END

    used = set(get_used_ports(db, server_id))

    if preferred_port and preferred_port not in used:
        return preferred_port

    # Find next available port
    for port in range(start, end + 1):
        if port not in used:
            logger.info(f"Assigned port {port} for server_id={server_id}")
            return port

    raise RuntimeError(f"No free ports available in range {start}-{end} for server {server_id}")


# Well-known protocol default ports for suggestions
PROTOCOL_DEFAULT_PORTS = {
    "vless_reality": 443,
    "trojan": 443,
    "naive_proxy": 8443,
}

# Reserved ports that should never be auto-assigned
RESERVED_PORTS = {22, 80, 443, 3306, 5432, 6379, 8080, 8443}
