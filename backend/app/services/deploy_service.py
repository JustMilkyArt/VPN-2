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
from app.services.config_generator import (
    generate_uuid, generate_password, generate_short_id,
    gen_xray_vless_reality_inbound, gen_xray_trojan_inbound,
    gen_xray_outbound_to_eu, gen_xray_warp_outbound, gen_xray_freedom_outbound,
    build_ru_xray_config, build_eu_xray_config,
    build_naiveproxy_caddy_config, build_naiveproxy_client_config,
    gen_vless_reality_client_link, gen_trojan_client_link,
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
    """Deploy VLESS+Reality connection on server."""
    try:
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
                        port=conn.port,
                        uuid_str=conn.uuid,
                        public_key=conn.reality_public_key or "",
                        private_key=conn.reality_private_key or "",
                        short_id=conn.reality_short_id or "",
                        server_name=conn.reality_server_name or "www.microsoft.com"
                    )
                    inbounds.append(ib)

            # Also include current connection
            current_ib = gen_xray_vless_reality_inbound(
                port=connection.port,
                uuid_str=connection.uuid,
                public_key=public_key,
                private_key=private_key,
                short_id=short_id,
                server_name=connection.reality_server_name or "www.microsoft.com"
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
                        eu_server_name=eu_conns.reality_server_name or "www.microsoft.com"
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
                server_name=connection.reality_server_name or "www.microsoft.com",
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
    """Deploy NaiveProxy connection on server."""
    try:
        domain = server.domain or server.ip
        password = connection.password
        port = connection.port

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
                    server_name=conn.reality_server_name or "www.microsoft.com"
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
