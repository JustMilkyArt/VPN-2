"""
Client API — public endpoints for the MilkyVPN Windows client.
Authentication: X-API-Key header (no login/TOTP required).
"""
import os
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.connection import Connection, ConnectionStatus
from app.models.server import Server, ServerRole

router = APIRouter(prefix="/client", tags=["client"])

# API key — must match AppConstants.clientApiKey in Flutter app
CLIENT_API_KEY = os.environ.get("CLIENT_API_KEY", "MilkyVPN-2025-xK9mP3nQ7rL5vW1jY8tA4bZ6dF0hE2")


def _verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != CLIENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


@router.get("/health", summary="Health check for client")
def client_health(_: None = Depends(_verify_api_key)):
    return {"status": "ok", "service": "MilkyVPN backend"}


@router.get("/connections", summary="Get all active connections for client")
def client_connections(
    db: Session = Depends(get_db),
    _: None = Depends(_verify_api_key),
):
    """
    Returns flat list of active connections with all fields needed by client.
    Ordered by: server country, protocol.
    """
    conns = (
        db.query(Connection)
        .filter(
            Connection.is_active == True,
            Connection.status == ConnectionStatus.ACTIVE,
        )
        .order_by(Connection.server_id, Connection.protocol)
        .all()
    )

    result = []
    for c in conns:
        srv = db.query(Server).filter(Server.id == c.server_id).first()
        if not srv:
            continue

        # Build display name
        flag = (srv.flag_emoji or "").strip()
        dname = (srv.display_name or srv.name or "").strip()
        proto_label = {
            "vless_reality": "VLESS+Reality",
            "amnezia_wg":    "AWG",
            "naive_proxy":   "NaiveProxy",
            "trojan":        "Trojan",
        }.get(str(c.protocol), str(c.protocol))

        conn_type_str = str(c.connection_type)  # "direct" or "cascade"

        parts = [p for p in [flag, dname] if p]
        name = (" ".join(parts) + f" | {proto_label}") if parts else proto_label

        # Determine entry point for client:
        #   cascade  → RU server (domain preferred, fallback to IP)
        #   direct   → EU server (domain preferred for NaiveProxy, IP for VLESS/AWG)
        proto_str = str(c.protocol)
        entry_ip = srv.domain or srv.ip  # prefer domain (valid TLS cert) for all protocols
        if conn_type_str == "cascade" and c.ru_server_id:
            ru_srv = db.query(Server).filter(Server.id == c.ru_server_id).first()
            if ru_srv:
                # For cascade NaiveProxy: use np_domain if set, else RU server domain/IP
                if proto_str == "naive_proxy" and c.np_domain:
                    entry_ip = c.np_domain
                else:
                    entry_ip = ru_srv.domain or ru_srv.ip
        else:
            # Direct connections
            if proto_str == "naive_proxy":
                # NaiveProxy MUST use domain (Caddy ACME cert bound to domain, not IP)
                entry_ip = c.np_domain or srv.domain or srv.ip
            elif proto_str in ("vless_reality", "amnezia_wg"):
                # VLESS/AWG connect to IP directly (Reality/WG don't need domain)
                entry_ip = srv.ip

        result.append({
            "id":                       c.id,
            "name":                     name,
            "protocol":                 str(c.protocol),
            "proto_label":              proto_label,
            "conn_type":                conn_type_str,
            "port":                     c.port,
            "server_ip":                entry_ip,
            "server_name":              dname,
            "server_country":           srv.country or "??",

            # Client link (vless://, naive+https://, awg://)
            "client_link":              c.client_link,

            # Full config text (AWG .conf or NaiveProxy JSON)
            "config_json":              c.config_text,

            # VLESS + Reality
            "uuid":                     c.uuid,
            "reality_public_key":       c.reality_public_key,
            "reality_short_id":         c.reality_short_id,
            "reality_server_name":      c.reality_server_name,

            # AmneziaWG
            "wg_public_key":            c.wg_public_key,
            "wg_client_private_key":    c.wg_client_private_key,
            "wg_client_public_key":     c.wg_client_public_key,
            "wg_preshared_key":         c.wg_preshared_key,
            "wg_client_ip":             c.wg_client_ip,
            "awg_junk_packet_count":    c.awg_junk_packet_count,
            "awg_junk_packet_min_size": c.awg_junk_packet_min_size,
            "awg_junk_packet_max_size": c.awg_junk_packet_max_size,

            # NaiveProxy / Trojan
            "password":                 c.password,
        })

    return result
