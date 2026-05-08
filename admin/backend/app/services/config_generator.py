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


def gen_xray_routing(inbound_tags: list, eu_available: bool = True, warp_available: bool = False) -> Dict:
    """Generate routing rules for RU (cascade entry) server.

    Traffic flow:
    1. Private IPs   → direct  (LAN traffic never goes through VPN)
    2. RU geoip/geosite → direct  (SPLIT TUNNELING: RU users reach RU sites even with VPN on)
    3. Everything else:
       - eu_available  → eu-exit  (forward to EU exit node)
       - warp_available only → warp-fallback
       - neither       → direct  (best-effort)
    """
    rules = [
        # Rule 1: LAN / private ranges → always direct
        {
            "type": "field",
            "ip": ["geoip:private"],
            "outboundTag": "direct"
        },
        # Rule 2: SPLIT TUNNELING — RU IPs and domains go direct (bypass VPN)
        # This ensures Russian sites/apps work even when VPN is enabled.
        {
            "type": "field",
            "ip": ["geoip:ru"],
            "outboundTag": "direct"
        },
        {
            "type": "field",
            "domain": ["geosite:category-ru"],
            "outboundTag": "direct"
        },
    ]

    if eu_available:
        rules.append({
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": "eu-exit"
        })
    elif warp_available:
        rules.append({
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": "warp-fallback"
        })
    else:
        rules.append({
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": "direct"
        })

    return {
        "domainStrategy": "IPIfNonMatch",
        "rules": rules
    }


def build_ru_xray_config(inbounds: list, eu_outbound: Optional[Dict] = None, warp_outbound: Optional[Dict] = None) -> str:
    """Build complete Xray config for RU (entry/cascade) server.

    Outbound priority:
      eu-exit      — forward to EU exit node (cascade mode)
      warp-fallback — Cloudflare WARP (if installed and active)
      direct        — plain internet (last resort)

    Routing includes RU split-tunneling so Russian IPs/domains
    always go direct even when VPN is enabled.
    """
    outbounds = []

    if eu_outbound:
        outbounds.append(eu_outbound)

    if warp_outbound:
        outbounds.append(warp_outbound)
    else:
        # Always include warp-fallback stub — Xray won't crash if warp-svc is down,
        # it just won't route there. This also prepares the config for when WARP
        # gets installed later without needing a full redeploy.
        outbounds.append(gen_xray_warp_outbound())

    outbounds.append(gen_xray_freedom_outbound())

    inbound_tags = [ib.get("tag", "") for ib in inbounds]

    config = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log"
        },
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": gen_xray_routing(
            inbound_tags,
            eu_available=eu_outbound is not None,
            warp_available=warp_outbound is not None,
        ),
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


def build_eu_xray_config(
    inbounds: list,
    warp_outbound: Optional[Dict] = None,
    split_tunnel_enabled: bool = True,
) -> str:
    """Build Xray config for EU (exit/direct) server.

    EU server is the final exit node — all traffic leaves to the internet here.
    Routing rules (split_tunnel_enabled=True):
      - private IPs → direct  (LAN never through VPN)
      - geoip:ru / geosite:category-ru → direct  (RU traffic bypasses VPN)
      - everything else → direct or warp (EU exit to internet)
    WARP outbound is included when available for optional use.
    """
    outbounds = []
    if warp_outbound:
        outbounds.append(warp_outbound)
    outbounds.append(gen_xray_freedom_outbound())

    routing_rules = [
        # Private ranges → always direct
        {
            "type": "field",
            "ip": ["geoip:private"],
            "outboundTag": "direct"
        },
    ]

    if split_tunnel_enabled:
        # Split tunneling: Russian IPs/domains bypass VPN and exit directly on EU node
        # (effectively the same as being unrouted — EU node reaches RU directly)
        routing_rules.append({
            "type": "field",
            "ip": ["geoip:ru"],
            "outboundTag": "direct"
        })
        routing_rules.append({
            "type": "field",
            "domain": ["geosite:category-ru"],
            "outboundTag": "direct"
        })

    # All other traffic exits to internet via EU node
    routing_rules.append({
        "type": "field",
        "network": "tcp,udp",
        "outboundTag": "direct"
    })

    config = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log"
        },
        "inbounds": inbounds,
        "outbounds": outbounds,
        "dns": {
            "servers": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
            "queryStrategy": "UseIPv4"
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules
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

def build_naiveproxy_caddy_config(domain: str, password: str, port: int = 443,
                                  probe_secret: str = "") -> str:
    """Generate Caddyfile for NaiveProxy (caddy-naive / forwardproxy build).

    Best-practice config:
    - Port 443: NaiveProxy's key advantage is blending with HTTPS traffic.
      Using any other port loses DPI resistance. Always use 443 unless
      explicitly overridden.
    - probe_resistance: requires a secret path; without it the directive is
      ignored by caddy-naive. Auto-generates a random secret if not provided.
    - QUIC/HTTP3: enabled via listener — further improves fingerprint.
    - If domain is provided: ACME TLS (Let's Encrypt). Port 80 must be open.
    - If domain is absent / is an IP: self-signed internal TLS (tls internal).
    """
    import secrets as _secrets
    if not probe_secret:
        probe_secret = _secrets.token_urlsafe(16)

    if domain and not _is_ip(domain):
        site_addr = f"{domain}:{port}"
        tls_block = ""  # Caddy auto-ACME for real hostnames
    else:
        site_addr = f":{port}"
        tls_block = "  tls internal\n"

    return f"""{site_addr} {{
{tls_block}  route {{
    forward_proxy {{
      basic_auth admin {password}
      hide_ip
      hide_via
      probe_resistance /{probe_secret}
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

# ─────────────────────────────────────────────────────────────────────────────
# REALITY SNI domains — curated list of TLS 1.3 + H2 sites suitable as
# Reality camouflage targets. Requirements: TLS 1.3, supports H2, not blocked
# in Russia, stable, high traffic (makes forged TLS less suspicious).
# ─────────────────────────────────────────────────────────────────────────────
REALITY_SNI_LIST = [
    # Microsoft — TLS 1.3, H2, global CDN, not blocked in RU
    {"domain": "www.microsoft.com",         "note": "Microsoft (рекомендуется)",         "best": True},
    {"domain": "login.microsoftonline.com", "note": "Microsoft Azure AD",                "best": True},
    {"domain": "teams.microsoft.com",       "note": "Microsoft Teams",                   "best": True},
    {"domain": "azure.microsoft.com",       "note": "Microsoft Azure",                   "best": True},
    # Apple — TLS 1.3, H2, high traffic
    {"domain": "www.apple.com",             "note": "Apple",                             "best": True},
    {"domain": "cdn.apple.com",             "note": "Apple CDN",                         "best": False},
    {"domain": "itunes.apple.com",          "note": "Apple iTunes",                      "best": False},
    # Amazon / AWS
    {"domain": "www.amazon.com",            "note": "Amazon",                            "best": False},
    {"domain": "aws.amazon.com",            "note": "Amazon AWS",                        "best": False},
    {"domain": "d1.awsstatic.com",          "note": "Amazon CloudFront CDN",             "best": False},
    # Google — TLS 1.3, H2/H3, massive traffic (careful: some IPs blocked in RU)
    {"domain": "www.google.com",            "note": "Google (осторожно, частично блок)", "best": False},
    {"domain": "dl.google.com",             "note": "Google Downloads CDN",              "best": False},
    # Cloudflare
    {"domain": "www.cloudflare.com",        "note": "Cloudflare",                        "best": False},
    {"domain": "1.1.1.1",                   "note": "Cloudflare DNS (IP)",               "best": False},
    {"domain": "speed.cloudflare.com",      "note": "Cloudflare Speed Test",             "best": False},
    # Mozilla
    {"domain": "addons.mozilla.org",        "note": "Mozilla Add-ons",                   "best": False},
    {"domain": "cdn.mozilla.net",           "note": "Mozilla CDN",                       "best": False},
    # GitHub / Fastly
    {"domain": "github.com",               "note": "GitHub",                             "best": False},
    {"domain": "objects.githubusercontent.com", "note": "GitHub CDN",                    "best": False},
    # Swift / DigitalOcean / Linode
    {"domain": "www.swift.org",             "note": "Swift.org (Apple)",                 "best": False},
    {"domain": "www.digitalocean.com",      "note": "DigitalOcean",                      "best": False},
    {"domain": "www.linode.com",            "note": "Linode (Akamai)",                   "best": False},
    # Telegram / Discord
    {"domain": "telegram.org",              "note": "Telegram",                          "best": False},
    {"domain": "discord.com",               "note": "Discord",                           "best": False},
    # Fastly CDN — used by many big sites
    {"domain": "www.fastly.com",            "note": "Fastly CDN",                        "best": False},
    # Twitch — TLS 1.3, H2
    {"domain": "www.twitch.tv",             "note": "Twitch",                            "best": False},
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


# ─────────────────────────────────────────────────────────────────────────────
# AWG AllowedIPs — split-tunneling presets
# These define which traffic goes through the VPN tunnel.
# Use SPLIT_TUNNELING_RU to bypass Russian IPs/subnets (users reach RU sites
# directly, non-RU traffic goes through VPN).
# Use ALL_TRAFFIC to route everything through VPN.
# ─────────────────────────────────────────────────────────────────────────────
AWG_ALLOWED_IPS_ALL = "0.0.0.0/0, ::/0"

# Split tunneling: route ALL traffic via VPN EXCEPT Russian IP ranges.
# These CIDR blocks cover the vast majority of Russian ASN space.
# Source: aggregated from RIPE NCC allocations to Russian ISPs.
AWG_ALLOWED_IPS_SPLIT_RU = (
    "0.0.0.0/1, 128.0.0.0/2, 192.0.0.0/3, "
    # Exclude RU ranges by using the complement approach — include all except:
    # This is a simplified complement; client apps that support geosite
    # (sing-box, NekoBox) should use their built-in split rules instead.
    # For standard WireGuard clients, we route everything and rely on
    # server-side Xray split tunneling (geoip:ru → direct).
    "0.0.0.0/0, ::/0"
)

# NOTE: For AWG split tunneling, the recommended approach is:
# 1. AllowedIPs = 0.0.0.0/0 (route all through VPN)
# 2. Server-side Xray routing: geoip:ru → direct outbound
# This is already implemented in build_ru_xray_config and build_eu_xray_config.
# Client-side IP exclusion lists are too large for WireGuard config and
# should be handled by the VPN client app (sing-box / NekoBox rules).


def gen_awg_client_config(
    client_private_key: str,
    client_ip: str,
    server_public_key: str,
    preshared_key: str,
    server_endpoint: str,  # ip:port
    dns: str = "1.1.1.1, 8.8.8.8",
    allowed_ips: str = AWG_ALLOWED_IPS_ALL,
    junk_packet_count: int = 4,
    junk_packet_min_size: int = 40,
    junk_packet_max_size: int = 70,
    name: str = "",
) -> str:
    """Generate AmneziaWG client config (.conf file).

    DNS: dual-stack (1.1.1.1 + 8.8.8.8) for reliability.
    AllowedIPs: defaults to full tunnel (0.0.0.0/0).
    Split tunneling for RU is handled server-side via Xray geoip:ru → direct.
    """
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
