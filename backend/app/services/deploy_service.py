"""
Deployment service - orchestrates SSH-based VPN stack deployment.
Manages installation, configuration, and service management on remote servers.
"""
import logging
import os
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.server import Server, ServerRole
from app.models.connection import Connection, Protocol
from app.services.ssh_service import SSHClient, test_connection
import random
from app.services.config_generator import (
    generate_uuid, generate_password, generate_short_id,
    gen_xray_vless_reality_inbound, gen_xray_trojan_inbound,
    gen_xray_outbound_to_eu, gen_xray_warp_outbound, gen_xray_freedom_outbound,
    build_ru_xray_config, build_eu_xray_config,
    build_naiveproxy_caddy_config, build_naiveproxy_client_config,
    gen_vless_reality_client_link, gen_trojan_client_link,
    gen_awg_server_config, gen_awg_client_config,
    get_reality_server_name,
)

logger = logging.getLogger(__name__)

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")


def _read_script(name: str) -> str:
    path = os.path.join(SCRIPTS_DIR, name)
    with open(path, "r") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# XRAY INSTALLATION
# ─────────────────────────────────────────────────────────────────────────────

XRAY_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing Xray-core..."
apt-get update -qq
apt-get install -y -qq curl wget unzip

# Install via official script
bash <(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install

# Create log directory
mkdir -p /var/log/xray
chmod 755 /var/log/xray

# Create config directory
mkdir -p /usr/local/etc/xray

# Create initial minimal config
cat > /usr/local/etc/xray/config.json << 'XRAY_EOF'
{
  "log": {"loglevel": "warning"},
  "inbounds": [],
  "outbounds": [{"tag":"direct","protocol":"freedom","settings":{}}]
}
XRAY_EOF

systemctl daemon-reload
systemctl enable xray
systemctl restart xray
echo "[+] Xray-core installed and started"
"""

GENERATE_REALITY_KEYS_CMD = "xray x25519"

WARP_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing Cloudflare WARP..."
apt-get install -y -qq curl

# Add Cloudflare GPG key and repo
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/cloudflare-client.list
apt-get update -qq
apt-get install -y -qq cloudflare-warp

# Register and connect WARP
warp-cli --accept-tos registration new || true
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect

echo "[+] WARP installed"
systemctl enable warp-svc
systemctl start warp-svc
"""


def install_xray(server: Server) -> Tuple[bool, str]:
    """Install Xray-core on a remote server."""
    try:
        with SSHClient(server) as ssh:
            logger.info(f"Installing Xray on {server.ip}")
            code, out, err = ssh.exec(XRAY_INSTALL_SCRIPT, timeout=300)
            if code != 0:
                return False, f"Xray install failed: {err}"
            return True, "Xray installed successfully"
    except Exception as e:
        return False, str(e)


def install_warp(server: Server) -> Tuple[bool, str]:
    """Install Cloudflare WARP on server."""
    try:
        with SSHClient(server) as ssh:
            logger.info(f"Installing WARP on {server.ip}")
            code, out, err = ssh.exec(WARP_INSTALL_SCRIPT, timeout=180)
            if code != 0:
                return False, f"WARP install failed: {err}"
            return True, "WARP installed"
    except Exception as e:
        return False, str(e)


def generate_reality_keys(server: Server) -> Tuple[Optional[str], Optional[str]]:
    """Generate Reality X25519 keypair on server using xray binary."""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec("xray x25519", timeout=30)
            if code != 0:
                logger.error(f"Key generation failed: {err}")
                return None, None
            
            private_key = None
            public_key = None
            for line in out.splitlines():
                if "Private key:" in line:
                    private_key = line.split(":", 1)[1].strip()
                elif "Public key:" in line:
                    public_key = line.split(":", 1)[1].strip()
            
            return private_key, public_key
    except Exception as e:
        logger.error(f"Key generation error: {e}")
        return None, None


def get_ssl_cert(server: Server, domain: str) -> Tuple[bool, str]:
    """Get/renew SSL certificate via acme.sh or certbot."""
    script = f"""#!/bin/bash
set -e
apt-get install -y -qq certbot
certbot certonly --standalone --agree-tos --no-eff-email \\
    -m admin@{domain} -d {domain} --non-interactive || \\
    certbot renew --force-renewal

mkdir -p /etc/ssl/xray
cp /etc/letsencrypt/live/{domain}/fullchain.pem /etc/ssl/xray/cert.pem
cp /etc/letsencrypt/live/{domain}/privkey.pem /etc/ssl/xray/key.pem
chmod 644 /etc/ssl/xray/cert.pem
chmod 600 /etc/ssl/xray/key.pem
echo "[+] SSL cert installed"
"""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(script, timeout=120)
            if code != 0:
                return False, f"SSL cert failed: {err}"
            return True, "SSL certificate installed"
    except Exception as e:
        return False, str(e)


def install_naiveproxy(server: Server, domain: str, password: str, port: int) -> Tuple[bool, str]:
    """Install and configure NaiveProxy (via Caddy) on server."""
    script = f"""#!/bin/bash
set -e

# Install Caddy with forward-proxy plugin (using xcaddy)
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-xcaddy-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/debian.deb.txt' > /etc/apt/sources.list.d/caddy-xcaddy.list
apt-get update -qq
apt-get install -y -qq xcaddy golang-go

# Build Caddy with forward_proxy
xcaddy build --with github.com/klzgrad/forwardproxy@latest --output /usr/local/bin/caddy
chmod +x /usr/local/bin/caddy

mkdir -p /etc/caddy /var/log/caddy /var/lib/caddy
"""

    caddy_config = build_naiveproxy_caddy_config(domain, password, port)

    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(script, timeout=600)
            if code != 0:
                return False, f"NaiveProxy install failed: {err}"
            
            # Upload Caddyfile
            ssh.upload_file(caddy_config, "/etc/caddy/Caddyfile")
            
            # Create systemd service
            service_content = """[Unit]
Description=Caddy NaiveProxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
LimitNOFILE=1048576
LimitNPROC=512
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
"""
            ssh.upload_file(service_content, "/etc/systemd/system/caddy-naive.service")
            code2, _, err2 = ssh.exec("systemctl daemon-reload && systemctl enable caddy-naive && systemctl restart caddy-naive")
            if code2 != 0:
                return False, f"Caddy service failed: {err2}"
            
            return True, "NaiveProxy installed"
    except Exception as e:
        return False, str(e)


def install_naiveproxy_no_domain(server: Server) -> Tuple[bool, str]:
    """Install NaiveProxy (Caddy binary only) without domain/config — domain will be added later."""
    script = """#!/bin/bash
set -e
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-xcaddy-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/debian.deb.txt' > /etc/apt/sources.list.d/caddy-xcaddy.list
apt-get update -qq
apt-get install -y -qq xcaddy golang-go
xcaddy build --with github.com/klzgrad/forwardproxy@latest --output /usr/local/bin/caddy
chmod +x /usr/local/bin/caddy
mkdir -p /etc/caddy /var/log/caddy /var/lib/caddy
echo "[+] NaiveProxy/Caddy binary installed (no domain configured yet)"
"""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(script, timeout=600)
            if code != 0:
                return False, f"NaiveProxy install failed: {err}"
            return True, "NaiveProxy (Caddy) installed — домен нужно добавить позже"
    except Exception as e:
        return False, str(e)


def install_amnezia_wg(server: Server) -> Tuple[bool, str]:
    """Install AmneziaWG on server (without creating a peer)."""
    try:
        with SSHClient(server) as ssh:
            _, check_out, _ = ssh.exec(
                "which awg 2>/dev/null && echo AWG_OK || (which wg 2>/dev/null && echo WG_OK || echo NOT_FOUND)"
            )
            if "NOT_FOUND" in check_out:
                code, _, err = ssh.exec(AWG_INSTALL_SCRIPT, timeout=300)
                if code != 0:
                    return False, f"AmneziaWG install failed: {err}"
                return True, "AmneziaWG установлен"
            elif "AWG_OK" in check_out:
                return True, "AmneziaWG уже установлен"
            else:
                return True, "WireGuard уже установлен (AmneziaWG fallback)"
    except Exception as e:
        return False, str(e)


def install_trojan(server: Server, password: str, port: int, domain: str) -> Tuple[bool, str]:
    """Install Trojan (via Xray) on server."""
    # Trojan runs through Xray inbound - just update config
    return True, "Trojan configured via Xray (see deploy_connection)"


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

def deploy_vless_reality_connection(
    db: Session,
    connection: Connection,
    server: Server,
    exit_server: Optional[Server] = None
) -> Tuple[bool, str]:
    """Deploy VLESS+Reality connection on server.
    
    Per spec:
    - TCP transport with TLS-Reality
    - Port 443
    - Flow: xtls-rprx-vision
    - serverName: chosen by server location/country
    """
    try:
        # Determine best serverName for this server's country/location
        server_name = (
            connection.reality_server_name
            or get_reality_server_name(server.country)
        )
        # VLESS Reality must always use port 443
        if not connection.port or connection.port == 0:
            connection.port = 443

        with SSHClient(server) as ssh:
            # Generate Reality keypair on the server
            code, key_out, key_err = ssh.exec("xray x25519", timeout=30)
            if code != 0:
                # Fallback: generate locally via subprocess
                import subprocess
                result = subprocess.run(["xray", "x25519"], capture_output=True, text=True)
                key_out = result.stdout

            private_key = public_key = None
            for line in key_out.splitlines():
                if "Private key:" in line:
                    private_key = line.split(":", 1)[1].strip()
                elif "Public key:" in line:
                    public_key = line.split(":", 1)[1].strip()

            if not private_key or not public_key:
                # Generate placeholder keys for now
                private_key = "auto-generated-run-xray-x25519"
                public_key = "auto-generated-run-xray-x25519"

            short_id = generate_short_id(16)
            connection.reality_private_key = private_key
            connection.reality_public_key = public_key
            connection.reality_short_id = short_id
            connection.reality_server_name = server_name

            # Get all active VLESS+Reality connections for this server to build full inbounds list
            all_connections = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.is_active == True,
                Connection.protocol == Protocol.VLESS_REALITY
            ).all()

            inbounds = []
            for conn in all_connections:
                if conn.uuid and conn.reality_private_key:
                    ib = gen_xray_vless_reality_inbound(
                        port=conn.port or 443,
                        uuid_str=conn.uuid,
                        public_key=conn.reality_public_key or "",
                        private_key=conn.reality_private_key or "",
                        short_id=conn.reality_short_id or "",
                        server_name=conn.reality_server_name or server_name
                    )
                    inbounds.append(ib)

            # Also include current connection
            current_ib = gen_xray_vless_reality_inbound(
                port=connection.port,
                uuid_str=connection.uuid,
                public_key=public_key,
                private_key=private_key,
                short_id=short_id,
                server_name=server_name
            )
            inbounds.append(current_ib)

            # Build EU outbound if exit server specified
            eu_outbound = None
            if exit_server:
                eu_conns = db.query(Connection).filter(
                    Connection.server_id == exit_server.id,
                    Connection.is_active == True,
                    Connection.protocol == Protocol.VLESS_REALITY
                ).first()
                if eu_conns and eu_conns.reality_public_key:
                    eu_outbound = gen_xray_outbound_to_eu(
                        eu_ip=exit_server.ip,
                        eu_port=eu_conns.port,
                        eu_uuid=eu_conns.uuid,
                        eu_public_key=eu_conns.reality_public_key,
                        eu_short_id=eu_conns.reality_short_id or "",
                        eu_server_name=eu_conns.reality_server_name or get_reality_server_name(exit_server.country)
                    )

            if server.role == ServerRole.RU:
                config_str = build_ru_xray_config(inbounds, eu_outbound=eu_outbound)
            else:
                config_str = build_eu_xray_config(inbounds)

            # Upload config and restart
            ssh.upload_file(config_str, "/usr/local/etc/xray/config.json")
            code2, _, err2 = ssh.exec("systemctl reload xray || systemctl restart xray")
            if code2 != 0:
                return False, f"Xray reload failed: {err2}"

            # Generate client link
            connection.client_link = gen_vless_reality_client_link(
                server_ip=server.ip,
                port=connection.port,
                uuid_str=connection.uuid,
                public_key=public_key,
                short_id=short_id,
                server_name=server_name,
                tag=connection.name
            )
            connection.config_json = config_str

            return True, "VLESS+Reality deployed"
    except Exception as e:
        logger.error(f"VLESS+Reality deploy error: {e}")
        return False, str(e)


def deploy_trojan_connection(
    db: Session,
    connection: Connection,
    server: Server,
) -> Tuple[bool, str]:
    """Deploy Trojan connection on server via Xray."""
    try:
        with SSHClient(server) as ssh:
            domain = server.domain or server.ip
            cert_file = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
            key_file = f"/etc/letsencrypt/live/{domain}/privkey.pem"

            # Check if cert exists, use self-signed fallback
            code, out, _ = ssh.exec(f"test -f {cert_file} && echo 'exists'")
            if "exists" not in out:
                cert_file = "/etc/ssl/xray/cert.pem"
                key_file = "/etc/ssl/xray/key.pem"
                # Create self-signed cert
                ssh.exec(f"""
mkdir -p /etc/ssl/xray
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \\
    -keyout {key_file} -out {cert_file} \\
    -subj '/CN={domain}' 2>/dev/null || true
""")

            # Get all trojan inbounds for this server
            all_conns = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.is_active == True,
                Connection.protocol == Protocol.TROJAN
            ).all()

            inbounds = []
            for conn in all_conns:
                if conn.password:
                    inbounds.append(gen_xray_trojan_inbound(conn.port, conn.password, cert_file, key_file))

            inbounds.append(gen_xray_trojan_inbound(connection.port, connection.password, cert_file, key_file))

            config_str = build_eu_xray_config(inbounds)
            ssh.upload_file(config_str, "/usr/local/etc/xray/config.json")
            code2, _, err2 = ssh.exec("systemctl reload xray || systemctl restart xray")
            if code2 != 0:
                return False, f"Xray reload failed: {err2}"

            connection.client_link = gen_trojan_client_link(
                server_ip=server.ip,
                port=connection.port,
                password=connection.password,
                sni=domain,
                tag=connection.name
            )
            connection.config_json = config_str
            return True, "Trojan deployed"
    except Exception as e:
        logger.error(f"Trojan deploy error: {e}")
        return False, str(e)


def deploy_naiveproxy_connection(
    db: Session,
    connection: Connection,
    server: Server,
) -> Tuple[bool, str]:
    """Deploy NaiveProxy connection on server.
    
    Per spec:
    - Requires a valid domain (not just IP)
    - TLS provisioned via Caddy + Let's Encrypt ACME
    - Always uses port 443
    """
    try:
        domain = server.domain
        if not domain:
            return False, (
                "NaiveProxy требует валидный домен. "
                "Добавьте домен в настройках сервера или привяжите поддомен через раздел Domains."
            )
        password = connection.password
        # NaiveProxy always on port 443 per spec
        port = 443
        connection.port = port

        ok, msg = install_naiveproxy(server, domain, password, port)
        if not ok:
            return False, msg

        # Build client config
        client_cfg = build_naiveproxy_client_config(domain, port, password)
        connection.config_json = client_cfg
        connection.client_link = f"https://admin:{password}@{domain}:{port}"

        return True, "NaiveProxy deployed"
    except Exception as e:
        logger.error(f"NaiveProxy deploy error: {e}")
        return False, str(e)


AWG_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing AmneziaWG..."

# Install amneziawg kernel module and tools
apt-get update -qq
apt-get install -y -qq software-properties-common

# Add AmneziaWG PPA (Ubuntu) or build from source
if add-apt-repository -y ppa:amnezia/ppa 2>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq amneziawg amneziawg-tools
else
    # Fallback: install standard WireGuard (AmneziaWG-compatible mode)
    apt-get install -y -qq wireguard wireguard-tools
fi

# Enable IP forwarding
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p

echo "[+] AmneziaWG installed"
"""


def _wg_genkey_on_server(ssh) -> Tuple[str, str]:
    """Generate WireGuard keypair on server, returns (private_key, public_key)."""
    # Try awg first, fallback to wg
    code, priv, _ = ssh.exec("awg genkey 2>/dev/null || wg genkey")
    priv = priv.strip()
    code2, pub, _ = ssh.exec(f"echo '{priv}' | awg pubkey 2>/dev/null || echo '{priv}' | wg pubkey")
    pub = pub.strip()
    return priv, pub


def _wg_preshared_on_server(ssh) -> str:
    code, psk, _ = ssh.exec("awg genpsk 2>/dev/null || wg genpsk")
    return psk.strip()


def _get_next_client_ip(db: Session, server_id: int) -> str:
    """Get next available client IP in 10.8.0.x/24 subnet."""
    existing = db.query(Connection).filter(
        Connection.server_id == server_id,
        Connection.protocol == Protocol.AMNEZIA_WG,
        Connection.wg_client_ip.isnot(None),
    ).all()
    used = set()
    for c in existing:
        if c.wg_client_ip:
            try:
                last_octet = int(c.wg_client_ip.split(".")[3].split("/")[0])
                used.add(last_octet)
            except Exception:
                pass
    for i in range(2, 255):
        if i not in used:
            return f"10.8.0.{i}"
    raise RuntimeError("No free client IPs in 10.8.0.0/24")


def deploy_amnezia_wg_connection(
    db: Session,
    connection: Connection,
    server: Server,
) -> Tuple[bool, str]:
    """Install AmneziaWG and deploy a WireGuard peer on server."""
    try:
        with SSHClient(server) as ssh:
            # Install AWG if not present
            code, _, _ = ssh.exec("which awg 2>/dev/null || which wg 2>/dev/null || echo NOT_FOUND")
            # We check the output
            _, check_out, _ = ssh.exec("which awg 2>/dev/null && echo AWG_OK || (which wg 2>/dev/null && echo WG_OK || echo NOT_FOUND)")
            if "NOT_FOUND" in check_out:
                code2, _, err2 = ssh.exec(AWG_INSTALL_SCRIPT, timeout=300)
                if code2 != 0:
                    return False, f"AmneziaWG install failed: {err2}"

            # Generate server keypair (or reuse existing)
            existing_server_conn = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.protocol == Protocol.AMNEZIA_WG,
                Connection.wg_private_key.isnot(None),
                Connection.id != connection.id,
            ).first()

            if existing_server_conn and existing_server_conn.wg_private_key:
                server_priv = existing_server_conn.wg_private_key
                server_pub = existing_server_conn.wg_public_key
            else:
                server_priv, server_pub = _wg_genkey_on_server(ssh)

            # Generate client keypair
            client_priv, client_pub = _wg_genkey_on_server(ssh)
            psk = _wg_preshared_on_server(ssh)

            # Assign client IP
            client_ip = _get_next_client_ip(db, server.id)

            # Save to connection — enforce spec values
            connection.wg_private_key = server_priv
            connection.wg_public_key = server_pub
            connection.wg_preshared_key = psk
            connection.wg_client_private_key = client_priv
            connection.wg_client_public_key = client_pub
            connection.wg_client_ip = client_ip
            connection.awg_junk_packet_count = 4                       # spec: 4
            connection.awg_junk_packet_min_size = 40                   # spec: 40
            connection.awg_junk_packet_max_size = 70                   # spec: 70
            # Generate random S1/S2 (15-150) once — same values used for server+client
            awg_s1 = random.randint(15, 150)
            awg_s2 = random.randint(15, 150)
            connection.awg_s1 = awg_s1  # persist for client re-generation
            connection.awg_s2 = awg_s2  # persist for client re-generation

            # Get all peers for this server
            all_awg = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.protocol == Protocol.AMNEZIA_WG,
                Connection.is_active == True,
                Connection.wg_client_public_key.isnot(None),
            ).all()

            clients_list = []
            for c in all_awg:
                if c.wg_client_public_key and c.wg_client_ip:
                    clients_list.append({
                        "pub_key": c.wg_client_public_key,
                        "preshared_key": c.wg_preshared_key or "",
                        "client_ip": c.wg_client_ip,
                    })
            # Add current
            clients_list.append({
                "pub_key": client_pub,
                "preshared_key": psk,
                "client_ip": client_ip,
            })

            # Generate and upload server config (S1/S2 shared with client)
            server_conf = gen_awg_server_config(
                server_private_key=server_priv,
                listen_port=connection.port,
                clients=clients_list,
                junk_packet_count=connection.awg_junk_packet_count,
                junk_packet_min_size=connection.awg_junk_packet_min_size,
                junk_packet_max_size=connection.awg_junk_packet_max_size,
                s1=awg_s1,
                s2=awg_s2,
            )
            ssh.upload_file(server_conf, "/etc/amnezia/amneziawg/wg0.conf")
            ssh.exec("mkdir -p /etc/amnezia/amneziawg || mkdir -p /etc/wireguard")

            # Try AWG first, fallback to WireGuard
            ssh.upload_file(server_conf, "/etc/amnezia/amneziawg/wg0.conf")
            code3, _, _ = ssh.exec(
                "systemctl enable awg-quick@wg0 2>/dev/null && awg-quick down wg0 2>/dev/null; awg-quick up wg0 2>/dev/null"
                " || (cp /etc/amnezia/amneziawg/wg0.conf /etc/wireguard/wg0.conf && "
                "systemctl enable wg-quick@wg0 && wg-quick down wg0 2>/dev/null; wg-quick up wg0)"
            )

            # Generate client config — MUST use same S1/S2 as server
            client_conf = gen_awg_client_config(
                client_private_key=client_priv,
                client_ip=client_ip,
                server_public_key=server_pub,
                preshared_key=psk,
                server_endpoint=f"{server.ip}:{connection.port}",
                junk_packet_count=connection.awg_junk_packet_count,
                junk_packet_min_size=connection.awg_junk_packet_min_size,
                junk_packet_max_size=connection.awg_junk_packet_max_size,
                s1=awg_s1,
                s2=awg_s2,
            )
            connection.config_json = client_conf
            connection.client_link = f"awg://peer?pub={server_pub}&endpoint={server.ip}:{connection.port}"

            return True, "AmneziaWG deployed"
    except Exception as e:
        logger.error(f"AmneziaWG deploy error: {e}")
        return False, str(e)


def redeploy_server_config(db: Session, server: Server) -> Tuple[bool, str]:
    """Re-deploy all active connections on a server (after restart etc.)."""
    connections = db.query(Connection).filter(
        Connection.server_id == server.id,
        Connection.is_active == True
    ).all()

    if not connections:
        return True, "No active connections to deploy"

    errors = []
    for conn in connections:
        if conn.config_json:
            try:
                with SSHClient(server) as ssh:
                    ssh.upload_file(conn.config_json, "/usr/local/etc/xray/config.json")
                    ssh.exec("systemctl reload xray || systemctl restart xray")
            except Exception as e:
                errors.append(str(e))

    if errors:
        return False, "; ".join(errors)
    return True, "Server configs re-deployed"


def restart_services(server: Server) -> Tuple[bool, str]:
    """Restart all VPN services on a server."""
    try:
        with SSHClient(server) as ssh:
            results = []
            for svc in ["xray", "caddy-naive", "warp-svc"]:
                code, _, err = ssh.exec(f"systemctl is-active {svc} && systemctl restart {svc} || true")
                results.append(f"{svc}: {'ok' if code == 0 else 'not running'}")
            return True, " | ".join(results)
    except Exception as e:
        return False, str(e)


def delete_connection_from_server(db: Session, connection: Connection, server: Server) -> Tuple[bool, str]:
    """Remove a connection from the server config."""
    try:
        # Get remaining connections
        remaining = db.query(Connection).filter(
            Connection.server_id == server.id,
            Connection.is_active == True,
            Connection.id != connection.id
        ).all()

        inbounds = []
        for conn in remaining:
            if conn.protocol == Protocol.VLESS_REALITY and conn.uuid and conn.reality_private_key:
                inbounds.append(gen_xray_vless_reality_inbound(
                    port=conn.port, uuid_str=conn.uuid,
                    public_key=conn.reality_public_key or "",
                    private_key=conn.reality_private_key or "",
                    short_id=conn.reality_short_id or "",
                    server_name=conn.reality_server_name or get_reality_server_name(server.country)
                ))
            elif conn.protocol == Protocol.TROJAN and conn.password:
                inbounds.append(gen_xray_trojan_inbound(conn.port, conn.password))

        config_str = build_eu_xray_config(inbounds)

        with SSHClient(server) as ssh:
            ssh.upload_file(config_str, "/usr/local/etc/xray/config.json")
            ssh.exec("systemctl reload xray || systemctl restart xray")

        return True, "Connection removed from server"
    except Exception as e:
        return False, str(e)
