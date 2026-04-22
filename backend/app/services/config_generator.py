"""
Configuration generator for Xray-core, NaiveProxy, and Trojan.
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
    return {
        "tag": f"vless-in-{port}",
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


def gen_xray_trojan_inbound(port: int, password: str, cert_file: str = "/etc/ssl/xray/cert.pem", key_file: str = "/etc/ssl/xray/key.pem") -> Dict:
    """Generate Xray Trojan inbound config."""
    return {
        "tag": f"trojan-in-{port}",
        "listen": "0.0.0.0",
        "port": port,
        "protocol": "trojan",
        "settings": {
            "clients": [{"password": password}]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {
                "certificates": [
                    {
                        "certificateFile": cert_file,
                        "keyFile": key_file
                    }
                ]
            }
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls"]
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
            "servers": ["8.8.8.8", "1.1.1.1", "localhost"]
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
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "ip": ["geoip:private"],
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
    tag: str = "VLESS-Reality"
) -> str:
    """Generate vless:// connection URI for clients."""
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
    tag_encoded = urllib.parse.quote(tag)
    return f"vless://{uuid_str}@{server_ip}:{port}?{query}#{tag_encoded}"


def gen_trojan_client_link(server_ip: str, port: int, password: str, sni: str, tag: str = "Trojan") -> str:
    """Generate trojan:// connection URI for clients."""
    import urllib.parse
    tag_encoded = urllib.parse.quote(tag)
    return f"trojan://{password}@{server_ip}:{port}?sni={sni}&security=tls#{tag_encoded}"


# ─────────────────────────────────────────────────────────────────────────────
# NAIVEPROXY CONFIG GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def build_naiveproxy_caddy_config(domain: str, password: str, port: int = 8443) -> str:
    """Generate Caddyfile for NaiveProxy."""
    return f"""{{
  servers {{
    protocol {{
      experimental_http3
    }}
  }}
}}

:{port}, {domain}:{port} {{
  tls {{
    on_demand
  }}
  route {{
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
    clients: list = None,  # list of {pub_key, preshared_key, client_ip}
    junk_packet_count: int = 4,
    junk_packet_min_size: int = 40,
    junk_packet_max_size: int = 70,
) -> str:
    """Generate AmneziaWG server wg0.conf"""
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
DNS = 1.1.1.1, 8.8.8.8

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

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
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
) -> str:
    """Generate AmneziaWG client config (.conf file)"""
    return f"""[Interface]
PrivateKey = {client_private_key}
Address = {client_ip}/32
DNS = {dns}

# AmneziaWG obfuscation (must match server)
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
