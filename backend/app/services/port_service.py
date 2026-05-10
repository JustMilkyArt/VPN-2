"""
Port management service - auto-assigns free ports and checks conflicts.

Port strategy for optimal DPI resistance:
  - NaiveProxy:     443  (HTTPS camouflage — mandatory for effectiveness)
  - VLESS+Reality:  443  (TLS camouflage — best on standard HTTPS port)
  - AmneziaWG:      51820 (standard WireGuard port) or random high port
  - If 443 is already taken on a server, fallback to high ports (10000+)

CASCADE PORT LOGIC:
  For cascade connections, the listening port is on the RU server (not EU).
  Therefore cascade port uniqueness must be checked against ru_server_id,
  not server_id (EU server).
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.connection import Connection, Protocol, ConnectionType

logger = logging.getLogger(__name__)


def get_used_ports(db: Session, server_id: int) -> List[int]:
    """Get all ports currently used on a server (EU role — direct connections)."""
    connections = db.query(Connection).filter(
        Connection.server_id == server_id,
        Connection.is_active == True
    ).all()
    return [c.port for c in connections if c.port]


def get_used_cascade_ports(db: Session, ru_server_id: int, protocol: Protocol) -> List[int]:
    """
    Get all cascade ports already allocated on a given RU server for a protocol.

    Cascade connections listen on the RU server — so uniqueness must be enforced
    per (ru_server_id, protocol), not per eu server_id.
    """
    rows = db.query(Connection.port).filter(
        Connection.ru_server_id == ru_server_id,
        Connection.protocol == protocol,
        Connection.connection_type == ConnectionType.CASCADE,
        Connection.is_active == True,
    ).all()
    return [r[0] for r in rows if r[0] is not None]


# Preferred ports per protocol — ordered by DPI-resistance priority.
PROTOCOL_PREFERRED_PORTS = {
    Protocol.NAIVE_PROXY:    [443, 8443, 2053, 2083, 2087, 2096],
    Protocol.VLESS_REALITY:  [2053, 2083, 2087, 2096, 8443],
    Protocol.AMNEZIA_WG:     [51820, 51821, 51822, 4500, 500],
}

# Port priorities by (protocol, connection_type).
PROTOCOL_PREFERRED_PORTS_BY_TYPE = {
    'naive_proxy_direct':    [443, 8443, 2053, 2083, 2087, 2096],
    'naive_proxy_cascade':   [8443, 8444, 2096, 2087, 2053],  # avoid 443 — EU server owns it
    'vless_reality_direct':  [2053, 2083, 2087, 2096, 8443],
    'vless_reality_cascade': [2087, 2088, 2089, 2083, 2053, 2096],
    'amnezia_wg_direct':     [51820, 51821, 51822, 4500, 500],
    'amnezia_wg_cascade':    [51821, 51822, 51823, 4500, 500],
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
    connection_type: Optional[str] = None,
    start: int = None,
    end: int = None,
    ru_server_id: Optional[int] = None,  # NEW: required for cascade port uniqueness
) -> int:
    """Assign a free port for a new connection.

    For CASCADE connections, port uniqueness is enforced against the RU server
    (ru_server_id), because that's where Xray/Caddy/AWG actually listens.

    For DIRECT connections, port uniqueness is enforced against the EU server
    (server_id).

    Selection priority:
    1. preferred_port (if provided and free)
    2. Protocol-optimal ports (443 for NaiveProxy/VLESS, 51820 for AWG)
    3. Dynamic range (PORT_RANGE_START..PORT_RANGE_END)
    """
    start = start or settings.PORT_RANGE_START
    end   = end   or settings.PORT_RANGE_END

    is_cascade = (connection_type in ('cascade', ConnectionType.CASCADE,
                                      'ConnectionType.CASCADE'))

    # Determine which server's ports to check against
    if is_cascade and ru_server_id:
        # CASCADE: port lives on RU server — check RU server used ports
        proto_enum = protocol
        if isinstance(protocol, str):
            # Convert string to Protocol enum if possible
            try:
                proto_enum = Protocol(protocol)
            except Exception:
                proto_enum = None

        if proto_enum:
            cascade_used = set(get_used_cascade_ports(db, ru_server_id, proto_enum))
        else:
            cascade_used = set()

        # Also include all connections on RU server (any protocol) to avoid collisions
        all_ru_ports = set(
            r[0] for r in db.query(Connection.port).filter(
                Connection.ru_server_id == ru_server_id,
                Connection.is_active == True,
            ).all() if r[0] is not None
        )
        used = all_ru_ports | cascade_used | RESERVED_PORTS
        logger.info(
            "assign_free_port CASCADE: ru_server_id=%s, used_ports=%s",
            ru_server_id, sorted(used)
        )
    else:
        # DIRECT: port lives on EU server — check EU server used ports
        used = set(get_used_ports(db, server_id)) | RESERVED_PORTS

    # 1. Honour explicit preferred port if free
    if preferred_port and preferred_port not in used:
        logger.info("Port %d assigned (explicit) for server_id=%d", preferred_port, server_id)
        return preferred_port

    # 2. Try protocol+type-optimal ports first
    if protocol:
        proto_key = protocol
        if hasattr(protocol, 'value'):
            proto_key = protocol.value
        ctype_key = connection_type or 'direct'
        if hasattr(ctype_key, 'value'):
            ctype_key = ctype_key.value
        # Normalise ConnectionType string
        if 'cascade' in str(ctype_key).lower():
            ctype_key = 'cascade'
        elif 'direct' in str(ctype_key).lower():
            ctype_key = 'direct'
        lookup_key = f"{proto_key}_{ctype_key}"

        pref_list_typed = PROTOCOL_PREFERRED_PORTS_BY_TYPE.get(lookup_key)
        if pref_list_typed:
            for p in pref_list_typed:
                if p not in used:
                    logger.info(
                        "Port %d assigned (protocol-optimal for %s/%s) for server_id=%d",
                        p, proto_key, ctype_key, server_id
                    )
                    return p

        # Fallback: generic protocol-optimal ports
        for proto_enum_key, pref_list in PROTOCOL_PREFERRED_PORTS.items():
            proto_val = proto_enum_key.value if hasattr(proto_enum_key, 'value') else proto_enum_key
            if proto_key == proto_val or proto_key == proto_enum_key:
                for p in pref_list:
                    if p not in used:
                        logger.info(
                            "Port %d assigned (protocol-optimal fallback for %s) for server_id=%d",
                            p, proto_key, server_id
                        )
                        return p
                break

    # 3. Dynamic range fallback
    for port in range(start, end + 1):
        if port not in used:
            logger.info("Port %d assigned (dynamic range) for server_id=%d", port, server_id)
            return port

    raise RuntimeError(
        f"No free ports available in range {start}-{end} for server {server_id}"
    )


# Legacy alias — kept for backwards compatibility
PROTOCOL_DEFAULT_PORTS = {
    "vless_reality": 443,
    "trojan":        443,
    "naive_proxy":   443,
    "amnezia_wg":    51820,
}
