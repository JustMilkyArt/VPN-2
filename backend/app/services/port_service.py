"""
Port management service - auto-assigns free ports and checks conflicts.

Port strategy for optimal DPI resistance:
  - NaiveProxy:     443  (HTTPS camouflage — mandatory for effectiveness)
  - VLESS+Reality:  443  (TLS camouflage — best on standard HTTPS port)
  - AmneziaWG:      51820 (standard WireGuard port) or random high port
  - If 443 is already taken on a server, fallback to high ports (10000+)
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.connection import Connection, Protocol

logger = logging.getLogger(__name__)


def get_used_ports(db: Session, server_id: int) -> List[int]:
    """Get all ports currently used on a server."""
    connections = db.query(Connection).filter(
        Connection.server_id == server_id,
        Connection.is_active == True
    ).all()
    return [c.port for c in connections]


# Preferred ports per protocol — ordered by DPI-resistance priority.
# These are tried first before falling back to the dynamic range.
PROTOCOL_PREFERRED_PORTS = {
    Protocol.NAIVE_PROXY:    [443, 8443, 2053, 2083, 2087, 2096],
    Protocol.VLESS_REALITY:  [443, 8443, 2053, 2083, 2087, 2096],
    Protocol.AMNEZIA_WG:     [51820, 51821, 51822, 4500, 500],
}

# Ports that should NEVER be auto-assigned (system services)
RESERVED_PORTS = {22, 80, 3306, 5432, 6379, 8080}

# Note: 443 and 8443 are intentionally NOT in RESERVED_PORTS —
# they are the optimal ports for NaiveProxy and VLESS Reality.


def assign_free_port(
    db: Session,
    server_id: int,
    preferred_port: Optional[int] = None,
    protocol: Optional[str] = None,
    start: int = None,
    end: int = None,
) -> int:
    """Assign a free port for a new connection.

    Selection priority:
    1. preferred_port (if provided and free)
    2. Protocol-optimal ports (443 for NaiveProxy/VLESS, 51820 for AWG)
    3. Dynamic range (PORT_RANGE_START..PORT_RANGE_END)

    Args:
        db:             DB session
        server_id:      Server ID to check port conflicts against
        preferred_port: Explicit port override (admin-specified)
        protocol:       Protocol enum value — used to pick optimal default port
        start/end:      Override dynamic range bounds
    """
    start = start or settings.PORT_RANGE_START
    end   = end   or settings.PORT_RANGE_END

    used = set(get_used_ports(db, server_id)) | RESERVED_PORTS

    # 1. Honour explicit preferred port if free
    if preferred_port and preferred_port not in used:
        logger.info(f"Port {preferred_port} assigned (explicit) for server_id={server_id}")
        return preferred_port

    # 2. Try protocol-optimal ports first
    if protocol:
        # Normalise to Protocol enum value string if needed
        proto_key = protocol
        if hasattr(protocol, 'value'):
            proto_key = protocol.value
        # Match against Protocol enum members
        for proto_enum, pref_list in PROTOCOL_PREFERRED_PORTS.items():
            proto_val = proto_enum.value if hasattr(proto_enum, 'value') else proto_enum
            if proto_key == proto_val or proto_key == proto_enum:
                for p in pref_list:
                    if p not in used:
                        logger.info(
                            f"Port {p} assigned (protocol-optimal for {proto_key}) "
                            f"for server_id={server_id}"
                        )
                        return p
                break  # Protocol matched but all preferred taken — fall through

    # 3. Dynamic range fallback
    for port in range(start, end + 1):
        if port not in used:
            logger.info(f"Port {port} assigned (dynamic range) for server_id={server_id}")
            return port

    raise RuntimeError(
        f"No free ports available in range {start}-{end} for server {server_id}"
    )


# Legacy alias — kept for backwards compatibility with existing callers
PROTOCOL_DEFAULT_PORTS = {
    "vless_reality": 443,
    "trojan":        443,
    "naive_proxy":   443,
    "amnezia_wg":    51820,
}
