"""
Configuration generator for Xray-core, NaiveProxy, and AmneziaWG.
Generates JSON/config files based on protocol and connection parameters.
"""
import json
import uuid
import secrets
import string
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_short_id(length: int = 8) -> str:
    """Generate Reality short ID (hex string)."""
    return secrets.token_hex(length // 2)


# ─────────────────────────────────────────────────────────────────────────────
# XRAY CONFIG GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def gen_xray_vless_reality_inbound(port: int, uuid_str: str, public_key: str, private_key: str, short_id: str, server_name: str = "www.microsoft.com") -> Dict:
    """Generate Xray VLESS + Reality inbound config."""
    # Tag must be unique across all inbounds in one config.
    # Two cascade connections from different EU servers can share the same port
    # on the RU server → use uuid prefix to guarantee uniqueness.
    tag = f"vless-in-{port}-{uuid_str[:8]}" if uuid_str else f"vless-in-{port}"
    return {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": port,
        "protocol": "vless",
        "settings": {
            "clients": [
                {
                    "id": uuid_str,
                    "flow": "xtls-rprx-vision"
                }
            ],
            "decryption": "none"
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "show": False,
                "dest": f"{server_name}:443",
                "xver": 0,
                "serverNames": [server_name],
                "privateKey": private_key,
                "shortIds": [short_id],
                "fingerprint": "chrome"
            }
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }



def gen_xray_outbound_to_eu(eu_ip: str, eu_port: int, eu_uuid: str, eu_public_key: str, eu_short_id: str, eu_server_name: str = "www.microsoft.com") -> Dict:
    """Generate Xray outbound (RU → EU) via VLESS+Reality."""
    return {
        "tag": "eu-exit",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": eu_ip,
                    "port": eu_port,
                    "users": [
                        {
                            "id": eu_uuid,
                            "flow": "xtls-rprx-vision",
                            "encryption": "none"
                        }
                    ]
                }
            ]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "show": False,
                "fingerprint": "chrome",
                "serverName": eu_server_name,
                "publicKey": eu_public_key,
                "shortId": eu_short_id,
                "spiderX": "/"
            }
        }
    }


def gen_xray_warp_outbound() -> Dict:
    """Generate WARP fallback outbound."""
    return {
        "tag": "warp-fallback",
        "protocol": "socks",
        "settings": {
            "servers": [
                {
                    "address": "127.0.0.1",
                    "port": 40000
                }
            ]
        }
    }


def gen_xray_freedom_outbound() -> Dict:
    """Direct internet outbound (for EU exit nodes)."""
    return {
        "tag": "direct",
        "protocol": "freedom",
        "settings": {}
    }


def gen_xray_routing(inbound_tags: list, eu_available: bool = True) -> Dict:
    """Generate routing rules."""
    rules = [
        {
            "type": "field",
            "ip": ["geoip:private"],
            "outboundTag": "direct"
        }
    ]

    if eu_available:
        rules.append({
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": "eu-exit"
        })
    else:
        rules.append({
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": "warp-fallback"
        })

    return {
        "domainStrategy": "IPIfNonMatch",
        "rules": rules
    }


def build_ru_xray_config(inbounds: list, eu_outbound: Optional[Dict] = None, warp_outbound: Optional[Dict] = None) -> str:
    """Build complete Xray config for RU (entry) server."""
    outbounds = [gen_xray_freedom_outbound()]
    
    if eu_outbound:
        outbounds.insert(0, eu_outbound)
    
    if warp_outbound:
        outbounds.append(warp_outbound)
    else:
        outbounds.append(gen_xray_warp_outbound())

    inbound_tags = [ib.get("tag", "") for ib in inbounds]
    
    config = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log"
        },
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": gen_xray_routing(inbound_tags, eu_available=eu_outbound is not None),
        "dns": {
            "servers": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
            "queryStrategy": "UseIPv4"
        },
        "policy": {
            "levels": {
                "0": {
                    "handshake": 4,
                    "connIdle": 300,
                    "uplinkOnly": 1,
                    "downlinkOnly": 1
                }
            }
        }
    }

    return json.dumps(config, indent=2)


def build_eu_xray_config(inbounds: list) -> str:
    """Build Xray config for EU (exit) server."""
    config = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log"
        },
        "inbounds": inbounds,
        "outbounds": [gen_xray_freedom_outbound()],
        "dns": {
            "servers": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
            "queryStrategy": "UseIPv4"
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "direct"
                },
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "outboundTag": "direct"
                }
            ]
        }
    }

    return json.dumps(config, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT LINK GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def gen_vless_reality_client_link(
    server_ip: str,
    port: int,
    uuid_str: str,
    public_key: str,
    short_id: str,
    server_name: str,
    server_flag: str = "",
    server_display_name: str = "",
    connection_type: str = "direct",
) -> str:
    """Generate vless:// connection URI for clients.

    Tag format: "{flag} {display_name} ({connection_type})"
    Example: "\U0001f1eb\U0001f1ee FIN 1 (direct)"
    """
    import urllib.parse
    params = {
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "security": "reality",
        "sni": server_name,
        "fp": "chrome",
        "pbk": public_key,
        "sid": short_id,
        "type": "tcp",
        "headerType": "none",
    }
    query = urllib.parse.urlencode(params)
    # Build human-readable tag (no emoji — many clients don't render them in URI tags)
    # Format: "FIN 1 | VLESS (direct)"
    name_part = server_display_name if server_display_name else server_ip
    tag = f"{name_part} | VLESS ({connection_type})"
    # Do NOT url-encode the tag — clients (V2Ray, sing-box) expect raw UTF-8 after #
    return f"vless://{uuid_str}@{server_ip}:{port}?{query}#{tag}"


# ─────────────────────────────────────────────────────────────────────────────
# NAIVEPROXY CONFIG GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def build_naiveproxy_caddy_config(domain: str, password: str, port: int = 8443) -> str:
    """Generate Caddyfile for NaiveProxy (caddy-naive / forwardproxy build).

    - If domain is provided: uses it with automatic ACME TLS (Let's Encrypt).
    - If domain is absent / is an IP: uses self-signed internal TLS (tls internal).
    """
    # Determine site address and TLS mode
    if domain and not _is_ip(domain):
        # Real domain → automatic ACME (Let's Encrypt).
        # caddy-naive fetches the cert on first request; port 80 must be reachable for HTTP-01.
        site_addr = f"{domain}:{port}"
        tls_block = ""          # Caddy auto-ACME when a hostname is given — no tls block needed
    else:
        # IP-only or no domain → self-signed internal cert
        site_addr = f":{port}"
        tls_block = "  tls internal\n"

    return f"""{site_addr} {{
{tls_block}  route {{
    forward_proxy {{
      basic_auth admin {password}
      hide_ip
      hide_via
      probe_resistance
    }}
    respond 404
  }}
}}
"""


def _is_ip(s: str) -> bool:
    """Return True if s looks like an IPv4/IPv6 address."""
    import re
    return bool(re.match(r'^[\d\.]+$', s) or re.match(r'^[0-9a-fA-F:]+$', s))


def build_naiveproxy_client_config(server: str, port: int, password: str) -> str:
    """Generate NaiveProxy client JSON config."""
    config = {
        "listen": "socks://127.0.0.1:1080",
        "proxy": f"https://admin:{password}@{server}:{port}",
        "log": ""
    }
    return json.dumps(config, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# REALITY SNI — TOP-10 BEST DOMAINS
# ─────────────────────────────────────────────────────────────────────────────

REALITY_SNI_LIST = [
    {"domain": "www.microsoft.com",     "note": "Microsoft — рекомендуется",  "best": True},
    {"domain": "addons.mozilla.org",    "note": "Mozilla",                    "best": False},
    {"domain": "www.swift.org",         "note": "Swift.org",                  "best": False},
    {"domain": "www.apple.com",         "note": "Apple",                      "best": False},
    {"domain": "www.amazon.com",        "note": "Amazon",                     "best": False},
    {"domain": "aws.amazon.com",        "note": "AWS",                        "best": False},
    {"domain": "telegram.org",          "note": "Telegram",                   "best": False},
    {"domain": "www.cloudflare.com",    "note": "Cloudflare",                 "best": False},
    {"domain": "www.digitalocean.com",  "note": "DigitalOcean",               "best": False},
    {"domain": "www.lovelace.com",      "note": "Lovelace",                   "best": False},
]

REALITY_SNI_DEFAULT = "www.microsoft.com"


# ─────────────────────────────────────────────────────────────────────────────
# AMNEZIA WIREGUARD CONFIG GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def gen_awg_server_config(
    server_private_key: str,
    server_ip: str = "10.8.0.1/24",
    listen_port: int = 51820,
    net_interface: str = "eth0",
    clients: list = None,  # list of {pub_key, preshared_key, client_ip}
    junk_packet_count: int = 4,
    junk_packet_min_size: int = 40,
    junk_packet_max_size: int = 70,
) -> str:
    """Generate AmneziaWG server wg0.conf.

    net_interface — реальное имя сетевого интерфейса сервера (eth0, ens3, enp0s3 и т.п.).
    Определяется автоматически через `ip route | grep default` перед генерацией.
    """
    clients = clients or []
    peers = ""
    for c in clients:
        peers += f"""
[Peer]
PublicKey = {c['pub_key']}
PresharedKey = {c['preshared_key']}
AllowedIPs = {c['client_ip']}/32
"""
    return f"""[Interface]
PrivateKey = {server_private_key}
Address = {server_ip}
ListenPort = {listen_port}

# AmneziaWG obfuscation
Jc = {junk_packet_count}
Jmin = {junk_packet_min_size}
Jmax = {junk_packet_max_size}
S1 = 50
S2 = 100
H1 = 1
H2 = 2
H3 = 3
H4 = 4

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o {net_interface} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o {net_interface} -j MASQUERADE
{peers}"""


def gen_awg_client_config(
    client_private_key: str,
    client_ip: str,
    server_public_key: str,
    preshared_key: str,
    server_endpoint: str,  # ip:port
    dns: str = "1.1.1.1",
    allowed_ips: str = "0.0.0.0/0, ::/0",
    junk_packet_count: int = 4,
    junk_packet_min_size: int = 40,
    junk_packet_max_size: int = 70,
    name: str = "",
) -> str:
    """Generate AmneziaWG client config (.conf file)"""
    name_line = f"Name = {name}\n" if name else ""
    return f"""[Interface]
{name_line}PrivateKey = {client_private_key}
Address = {client_ip}/32
DNS = {dns}
Jc = {junk_packet_count}
Jmin = {junk_packet_min_size}
Jmax = {junk_packet_max_size}
S1 = 50
S2 = 100
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = {server_public_key}
PresharedKey = {preshared_key}
Endpoint = {server_endpoint}
AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
"""
