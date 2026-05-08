"""
Subscription endpoint — sing-box 1.11.x.
Без geoip/geosite rule_set — не нужны для не-CN пользователей.
"""

import base64
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.connection import Connection, Protocol, ConnectionStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subscribe", tags=["subscribe"])


def _get_connections(db: Session):
    return (
        db.query(Connection)
        .filter(
            Connection.is_active == True,
            Connection.status == ConnectionStatus.ACTIVE,
        )
        .all()
    )


def _client_name(conn: Connection) -> str:
    server = conn.server
    display = getattr(server, "display_name", "") or server.name or server.ip
    proto_label = {
        "vless_reality": "VLESS",
        "amnezia_wg":    "AWG",
        "naive_proxy":   "NaiveProxy",
    }.get(conn.protocol, conn.protocol.upper())
    conn_type = "direct" if conn.connection_type == "direct" else "cascade"
    return f"{display} | {proto_label} ({conn_type})"


def _singbox_vless(conn: Connection) -> dict | None:
    if not conn.client_link:
        return None
    return {
        "type": "vless",
        "tag": _client_name(conn),
        "server": conn.server.ip,
        "server_port": conn.port,
        "uuid": conn.uuid,
        "flow": "xtls-rprx-vision",
        "tls": {
            "enabled": True,
            "server_name": conn.reality_server_name or "www.microsoft.com",
            "utls": {"enabled": True, "fingerprint": conn.reality_fingerprint or "chrome"},
            "reality": {
                "enabled": True,
                "public_key": conn.reality_public_key,
                "short_id": conn.reality_short_id,
            },
        },
    }


def _singbox_naive(conn: Connection) -> dict | None:
    if not conn.np_domain or not conn.password:
        return None
    return {
        "type": "http",
        "tag": _client_name(conn),
        "server": conn.np_domain,
        "server_port": conn.port,
        "username": "admin",
        "password": conn.password,
        "tls": {"enabled": True, "server_name": conn.np_domain},
    }


def _singbox_awg(conn: Connection) -> dict | None:
    return None


def _build_singbox(conns: list) -> dict:
    outbounds = []
    tags = []

    builders = {
        Protocol.VLESS_REALITY: _singbox_vless,
        Protocol.NAIVE_PROXY:   _singbox_naive,
        Protocol.AMNEZIA_WG:    _singbox_awg,
    }

    for conn in conns:
        proto = Protocol(conn.protocol)
        builder = builders.get(proto)
        if builder:
            ob = builder(conn)
            if ob:
                outbounds.append(ob)
                tags.append(ob["tag"])

    outbounds.insert(0, {
        "type": "selector",
        "tag": "proxy",
        "outbounds": (tags + ["direct"]) if tags else ["direct"],
    })
    outbounds.append({"type": "direct", "tag": "direct"})

    return {
        "log": {"level": "info"},
        "dns": {
            "servers": [
                {"tag": "remote", "address": "1.1.1.1",   "detour": "direct"},
                {"tag": "local",  "address": "8.8.8.8",   "detour": "direct"},
            ],
            "final": "remote",
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": "tun0",
                "address": "172.19.0.1/30",
                "auto_route": True,
                "strict_route": True,
                "sniff": True,
            }
        ],
        "outbounds": outbounds,
        "route": {
            "rules": [
                # DNS перехват
                {"protocol": "dns", "action": "hijack-dns"},
                # UDP → direct: NaiveProxy (type:http) не поддерживает UDP
                {"network": "udp", "outbound": "direct"},
                # Локальные адреса напрямую
                {"ip_cidr": ["127.0.0.0/8", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"], "outbound": "direct"},
            ],
            "final": "proxy",
            "auto_detect_interface": True,
        },
    }


def _build_clash(conns: list) -> str:
    lines = ["mixed-port: 7890", "allow-lan: false", "mode: rule", "log-level: info", "", "proxies:"]
    proxy_names = []

    for conn in conns:
        name = _client_name(conn)
        proto = conn.protocol

        if proto == "vless_reality":
            lines.append(
                f'  - name: "{name}"\n    type: vless\n    server: {conn.server.ip}\n'
                f'    port: {conn.port}\n    uuid: {conn.uuid}\n    network: tcp\n'
                f'    tls: true\n    flow: xtls-rprx-vision\n'
                f'    servername: {conn.reality_server_name or "www.microsoft.com"}\n'
                f'    reality-opts:\n      public-key: {conn.reality_public_key}\n'
                f'      short-id: {conn.reality_short_id}\n'
                f'    client-fingerprint: {conn.reality_fingerprint or "chrome"}'
            )
            proxy_names.append(name)

        elif proto == "naive_proxy" and conn.np_domain and conn.password:
            lines.append(
                f'  - name: "{name}"\n    type: http\n    server: {conn.np_domain}\n'
                f'    port: {conn.port}\n    username: admin\n    password: {conn.password}\n'
                f'    tls: true\n    skip-cert-verify: false'
            )
            proxy_names.append(name)

    proxy_list = "\n".join(f'      - "{n}"' for n in proxy_names) or '      - DIRECT'
    lines += [
        "", "proxy-groups:",
        f'  - name: "🚀 Proxy"\n    type: select\n    proxies:\n{proxy_list}\n      - DIRECT',
        "", "rules:", "  - MATCH,🚀 Proxy",
    ]
    return "\n".join(lines)


def _build_raw(conns: list) -> str:
    uris = [conn.client_link or conn.config_text for conn in conns if conn.client_link or conn.config_text]
    return base64.b64encode("\n".join(uris).encode()).decode()


def _validate_token(token: str, db: Session) -> bool:
    try:
        decoded = base64.b64decode(token + "==").decode("utf-8")
    except Exception:
        return False
    return decoded in {"vpn:milkyims2024", "vpn:admin"}


@router.get("/{token}")
def get_subscription(
    token: str,
    format: str = Query(default="singbox", description="singbox | clash | raw"),
    db: Session = Depends(get_db),
):
    if not _validate_token(token, db):
        raise HTTPException(status_code=403, detail="Неверный токен подписки")

    conns = _get_connections(db)

    if format == "singbox":
        return Response(
            content=json.dumps(_build_singbox(conns), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=config.json"},
        )
    elif format == "clash":
        return Response(
            content=_build_clash(conns),
            media_type="text/yaml; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=clash.yaml"},
        )
    elif format == "raw":
        return PlainTextResponse(content=_build_raw(conns))
    else:
        raise HTTPException(status_code=400, detail="format должен быть: singbox, clash, raw")
