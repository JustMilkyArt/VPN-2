"""
Client API — read-only endpoint for the VPN Windows client app.
No admin auth required; protected by a static API key baked into the client binary.

GET /api/v1/client/connections   — list of active connections with full client configs
GET /api/v1/client/health        — heartbeat / version check
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from typing import Optional, List

from app.db.database import get_db
from app.models.connection import Connection, Protocol, ConnectionStatus
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/client", tags=["client"])

# API key — read from env (set in .env on the server).
# The same key is compiled into the Flutter client binary.
_CLIENT_API_KEY = os.environ.get("CLIENT_API_KEY", "")


def _verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """Dependency: reject requests without a valid API key."""
    if not _CLIENT_API_KEY:
        # Key not configured on server — fail closed for safety
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Client API not configured (CLIENT_API_KEY missing in server env)",
        )
    if x_api_key != _CLIENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


def _connection_to_dict(conn: Connection, server: Server) -> dict:
    """Serialize a connection to the payload the Flutter client needs."""
    # Determine connection type label for display
    is_cascade = conn.exit_server_id is not None
    conn_type = "cascade" if is_cascade else "direct"

    # Protocol display name
    proto_names = {
        Protocol.VLESS_REALITY: "VLESS + Reality",
        Protocol.AMNEZIA_WG:   "AmneziaWG",
        Protocol.NAIVE_PROXY:  "NaiveProxy",
        Protocol.TROJAN:       "Trojan",
    }
    proto_label = proto_names.get(conn.protocol, conn.protocol)

    payload = {
        "id":           conn.id,
        "name":         conn.name,
        "protocol":     conn.protocol,
        "proto_label":  proto_label,
        "conn_type":    conn_type,          # "direct" | "cascade"
        "port":         conn.port,
        "status":       conn.status,
        "server_ip":    server.ip,
        "server_name":  server.name,
        "server_country": server.country,
        # Client link (URI scheme — vless://, trojan://, etc.)
        "client_link":  conn.client_link,
        # Full text config (JSON for xray/naive, INI for AWG)
        "config_json":  conn.config_json,
        # VLESS + Reality
        "uuid":                 conn.uuid,
        "reality_public_key":   conn.reality_public_key,
        "reality_short_id":     conn.reality_short_id,
        "reality_server_name":  conn.reality_server_name,
        # AmneziaWG
        "wg_public_key":            conn.wg_public_key,
        "wg_client_private_key":    conn.wg_client_private_key,
        "wg_client_public_key":     conn.wg_client_public_key,
        "wg_preshared_key":         conn.wg_preshared_key,
        "wg_client_ip":             conn.wg_client_ip,
        "awg_junk_packet_count":    conn.awg_junk_packet_count,
        "awg_junk_packet_min_size": conn.awg_junk_packet_min_size,
        "awg_junk_packet_max_size": conn.awg_junk_packet_max_size,
        # NaiveProxy / Trojan
        "password": conn.password,
    }
    return payload


@router.get("/health")
def client_health():
    """Heartbeat — client uses this to check backend reachability."""
    return {"ok": True, "version": "1.0"}


@router.get("/connections")
def list_client_connections(
    db: Session = Depends(get_db),
    _: None = Depends(_verify_api_key),
) -> List[dict]:
    """
    Return all active connections with full client configs.
    Only connections with status=active and is_active=True are returned.
    """
    conns = (
        db.query(Connection)
        .filter(
            Connection.is_active == True,
            Connection.status == ConnectionStatus.ACTIVE,
        )
        .order_by(Connection.id)
        .all()
    )

    result = []
    for conn in conns:
        server = db.query(Server).filter(Server.id == conn.server_id).first()
        if not server:
            continue
        result.append(_connection_to_dict(conn, server))

    logger.info(f"Client API: returned {len(result)} active connections")
    return result
