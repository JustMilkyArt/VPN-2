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
    gen_xray_vless_reality_inbound,
    gen_xray_outbound_to_eu, gen_xray_warp_outbound, gen_xray_freedom_outbound,
    build_ru_xray_config, build_eu_xray_config,
    build_naiveproxy_caddy_config, build_naiveproxy_client_config,
    gen_vless_reality_client_link,
    gen_awg_server_config, gen_awg_client_config,
)

logger = logging.getLogger(__name__)

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")


def _read_script(name: str) -> str:
    path = os.path.join(SCRIPTS_DIR, name)
    with open(path, "r") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# SERVER PREPARATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_server_ready(ssh, port: int, proto: str = "tcp") -> None:
    """
    Выполняется перед каждым деплоем подключения на сервер.
    Настраивает:
      1. IP-forwarding (сохраняется в sysctl.conf)
      2. /etc/resolv.conf — реальные DNS вместо systemd-resolved stub
      3. UFW — открывает порт подключения
    Все операции идемпотентны (повторный запуск безопасен).
    """
    # 1. IP forwarding
    ssh.exec(
        "grep -q 'net.ipv4.ip_forward=1' /etc/sysctl.conf || "
        "echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf; "
        "grep -q 'net.ipv6.conf.all.forwarding=1' /etc/sysctl.conf || "
        "echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf; "
        "sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1; "
        "sysctl -w net.ipv6.conf.all.forwarding=1 > /dev/null 2>&1"
    )

    # 2. Исправляем /etc/resolv.conf — убираем stub-resolver если он там
    ssh.exec(
        "if grep -q '127.0.0.53' /etc/resolv.conf 2>/dev/null || "
        "[ -L /etc/resolv.conf ]; then "
        "  rm -f /etc/resolv.conf; "
        "  printf 'nameserver 1.1.1.1\\nnameserver 8.8.8.8\\nnameserver 8.8.4.4\\n' "
        "    > /etc/resolv.conf; "
        "  systemctl disable systemd-resolved 2>/dev/null || true; "
        "  systemctl stop systemd-resolved 2>/dev/null || true; "
        "fi"
    )

    # 3. UFW — открываем порт (если UFW активен)
    ufw_proto = "udp" if proto == "udp" else "tcp"
    ssh.exec(
        f"if command -v ufw > /dev/null 2>&1 && ufw status | grep -q 'Status: active'; then "
        f"  ufw allow {port}/{ufw_proto} > /dev/null 2>&1 || true; "
        f"fi"
    )


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
# Запускаем через sudo если не root
_SUDO=""
[ "$(id -u)" != "0" ] && _SUDO="sudo -n"

$_SUDO apt-get install -y -qq curl

# Add Cloudflare GPG key and repo
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | $_SUDO gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | $_SUDO tee /etc/apt/sources.list.d/cloudflare-client.list > /dev/null
$_SUDO apt-get update -qq
$_SUDO apt-get install -y -qq cloudflare-warp

# Register and connect WARP
warp-cli --accept-tos registration new || true
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect

echo "[+] WARP installed"
$_SUDO systemctl enable warp-svc
$_SUDO systemctl start warp-svc
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


# ─── Bash script to install caddy-naive binary (shared) ────────────────────
_CADDY_INSTALL_SCRIPT = r"""#!/bin/bash
set -e

apt-get install -y -qq curl tar

# Detect architecture
ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
case "$ARCH" in
  amd64|x86_64) IS_AMD64=1 ;;
  *) IS_AMD64=0 ;;
esac

if [ -f /usr/local/bin/caddy-naive ]; then
    echo "[+] caddy-naive already installed: $(/usr/local/bin/caddy-naive version 2>/dev/null || echo unknown)"
else
  cd /tmp
  rm -f caddy-naive.tar.xz

  if [ "$IS_AMD64" = "1" ]; then
      FP_VER=$(curl -sf "https://api.github.com/repos/klzgrad/forwardproxy/releases/latest"           | grep '"tag_name"' | cut -d'"' -f4 | head -1)
      [ -z "$FP_VER" ] && FP_VER="v2.10.0-naive"
      echo "[+] forwardproxy version: $FP_VER"
      CADDY_URL="https://github.com/klzgrad/forwardproxy/releases/download/${FP_VER}/caddy-forwardproxy-naive.tar.xz"
      echo "[+] Downloading: $CADDY_URL"
      curl -fsSL --retry 3 --retry-delay 2 -o caddy-naive.tar.xz "$CADDY_URL"
      tar -xJf caddy-naive.tar.xz 2>/dev/null || tar -xf caddy-naive.tar.xz 2>/dev/null || true
      CADDY_BIN=$(find /tmp/caddy-forwardproxy-naive -name "caddy" -type f 2>/dev/null | head -1)
      [ -z "$CADDY_BIN" ] && CADDY_BIN=$(find /tmp -maxdepth 3 -name "caddy" -type f 2>/dev/null | head -1)
      if [ -z "$CADDY_BIN" ]; then
          echo "ERROR: caddy binary not found in archive"; exit 1
      fi
  else
      # arm64 fallback: build with xcaddy
      apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-xcaddy-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/debian.deb.txt' > /etc/apt/sources.list.d/caddy-xcaddy.list
      apt-get update -qq && apt-get install -y -qq xcaddy golang-go
      xcaddy build --with github.com/klzgrad/forwardproxy@latest --output /tmp/caddy
      CADDY_BIN="/tmp/caddy"
  fi

  cp "$CADDY_BIN" /usr/local/bin/caddy-naive
  chmod +x /usr/local/bin/caddy-naive
  echo "[+] caddy-naive installed: $(/usr/local/bin/caddy-naive version 2>/dev/null || echo unknown)"
fi

mkdir -p /etc/caddy /var/log/caddy /var/lib/caddy
echo "[+] Done"
"""

_CADDY_SERVICE = """[Unit]
Description=Caddy NaiveProxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/local/bin/caddy-naive run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy-naive reload --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
LimitNOFILE=1048576
LimitNPROC=512
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
"""


def install_caddy_naive_binary(server: Server) -> Tuple[bool, str]:
    """Install only the caddy-naive binary (without Caddyfile/service).
    Called from install_stack when user installs NaiveProxy stack component."""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(_CADDY_INSTALL_SCRIPT, timeout=300)
            if code != 0:
                return False, f"caddy-naive install failed: {err or out}"
            # Record version
            code2, ver_out, _ = ssh.exec(
                "/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || echo ''"
            )
            ver = (ver_out or "").strip().splitlines()[0] if ver_out else "installed"
            return True, f"caddy-naive installed ({ver})"
    except Exception as e:
        return False, str(e)


def install_naiveproxy(server: Server, domain: str, password: str, port: int) -> Tuple[bool, str]:
    """Install caddy-naive binary AND deploy Caddyfile + systemd service for a specific connection.
    Called from deploy_naiveproxy_connection."""
    try:
        with SSHClient(server) as ssh:
            # 1. Install binary
            code, out, err = ssh.exec(_CADDY_INSTALL_SCRIPT, timeout=300)
            if code != 0:
                return False, f"caddy-naive install failed: {err or out}"

            # 2. Upload Caddyfile
            caddy_config = build_naiveproxy_caddy_config(domain, password, port)
            ssh.upload_file(caddy_config, "/etc/caddy/Caddyfile")

            # 3. Install systemd service
            ssh.upload_file(_CADDY_SERVICE, "/etc/systemd/system/caddy-naive.service")
            code2, _, err2 = ssh.exec(
                "systemctl daemon-reload && systemctl enable caddy-naive && systemctl restart caddy-naive"
            )
            if code2 != 0:
                return False, f"Caddy service failed: {err2}"

            return True, "NaiveProxy deployed"
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

def deploy_vless_reality_connection(
    db: Session,
    connection: Connection,
    server: Server,
    exit_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """Deploy VLESS+Reality connection on server."""
    try:
        with SSHClient(server) as ssh:
            # Prepare server: ip_forward, DNS, UFW port
            _ensure_server_ready(ssh, connection.port, proto="tcp")

            # Generate Reality keypair on the server
            code, key_out, key_err = ssh.exec("xray x25519", timeout=30)
            if code != 0:
                # Fallback: generate locally via subprocess
                import subprocess
                result = subprocess.run(["xray", "x25519"], capture_output=True, text=True)
                key_out = result.stdout

            private_key = public_key = None
            for line in key_out.splitlines():
                line = line.strip()
                # xray версии 1.x: "Private key: ..." / "Public key: ..."
                # xray версии 24.x+: "PrivateKey: ..." / "Password (PublicKey): ..."
                if line.startswith("Private key:"):
                    private_key = line.split(":", 1)[1].strip()
                elif line.startswith("Public key:"):
                    public_key = line.split(":", 1)[1].strip()
                elif line.startswith("PrivateKey:"):
                    private_key = line.split(":", 1)[1].strip()
                elif line.startswith("Password (PublicKey):"):
                    public_key = line.split(":", 1)[1].strip()

            if not private_key or not public_key:
                logger.error(f"xray x25519 output was: {key_out!r}")
                return False, "Не удалось сгенерировать Reality keypair (xray x25519 вернул неожиданный формат)"

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

            # NOTE: current connection is already included in all_connections above
            # (keys were saved to DB before the query), so no extra append needed.
            # If for some reason it's missing (e.g. new unsaved connection), add it.
            current_ids = {conn.id for conn in all_connections}
            if connection.id not in current_ids:
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

            # Generate client link with server flag and display name
            connection.client_link = gen_vless_reality_client_link(
                server_ip=server.ip,
                port=connection.port,
                uuid_str=connection.uuid,
                public_key=public_key,
                short_id=short_id,
                server_name=connection.reality_server_name or "www.microsoft.com",
                server_flag=getattr(server, 'flag_emoji', '') or '',
                server_display_name=getattr(server, 'display_name', '') or server.name or '',
                connection_type="cascade" if is_cascade else "direct",
            )
            connection.config_json = config_str
            db.commit()

            return True, "VLESS+Reality deployed"
    except Exception as e:
        logger.error(f"VLESS+Reality deploy error: {e}")
        return False, str(e)


def deploy_naiveproxy_connection(
    db: Session,
    connection: Connection,
    server: Server,
    ru_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """
    Deploy NaiveProxy connection.

    DIRECT  (is_cascade=False):
        Клиент ──[NaiveProxy/HTTPS]──► EU сервер (caddy-naive) ──► интернет
        Caddy-naive ставится на EU сервере (server).
        Домен: server.domain (eu.milkyims.com).

    CASCADE (is_cascade=True):
        Клиент ──[NaiveProxy/HTTPS]──► RU сервер (caddy-naive)
                                            ├──[VLESS]──► EU сервер ──► зарубежный интернет
                                            ├──[direct]─────────────► российский интернет
                                            └──[WARP fallback]───────► Cloudflare
        Caddy-naive ставится на RU сервере (ru_server).
        Xray на RU получает VLESS inbound + outbound на EU + WARP fallback.
        Домен: ru_server.domain (ru.milkyims.com).
    """
    def _log(msg: str):
        """Append message to connection setup_log."""
        cur = connection.setup_log or ""
        connection.setup_log = cur + f"[NaiveProxy] {msg}\n"
        db.commit()

    try:
        password = connection.password
        port     = connection.port

        # ── Определяем целевой сервер и домен ────────────────────────────────
        if is_cascade:
            if not ru_server:
                return False, "CASCADE: ru_server не передан"
            target_server = ru_server
            domain = ru_server.domain or ru_server.ip
            _log(f"Режим: CASCADE. Caddy-naive → RU сервер ({domain})")
        else:
            target_server = server
            domain = server.domain or server.ip
            _log(f"Режим: DIRECT. Caddy-naive → EU сервер ({domain})")

        # ── Шаг 1: Установка caddy-naive на целевой сервер ───────────────────
        _log(f"Шаг 1: Установка caddy-naive на {target_server.name} ({target_server.ip})")
        with SSHClient(target_server) as ssh:
            # Prepare server: ip_forward, DNS, UFW port
            _ensure_server_ready(ssh, connection.port, proto="tcp")

            code, out, err = ssh.exec(_CADDY_INSTALL_SCRIPT, timeout=300)
            if code != 0:
                return False, f"caddy-naive install failed: {err or out}"
            version_line = [l for l in out.splitlines() if "caddy-naive installed" in l or "already installed" in l]
            _log(f"  caddy-naive: {version_line[-1] if version_line else 'установлен'}")

            # ── Шаг 2: Генерация и загрузка Caddyfile ────────────────────────
            _log(f"Шаг 2: Генерация Caddyfile (домен={domain}, порт={port})")
            caddy_config = build_naiveproxy_caddy_config(domain, password, port)
            ssh.upload_file(caddy_config, "/etc/caddy/Caddyfile")
            _log(f"  Caddyfile загружен: /etc/caddy/Caddyfile")

            # ── Шаг 3: Systemd-сервис caddy-naive ────────────────────────────
            _log("Шаг 3: Настройка systemd-сервиса caddy-naive")
            ssh.upload_file(_CADDY_SERVICE, "/etc/systemd/system/caddy-naive.service")
            code2, _, err2 = ssh.exec(
                "systemctl daemon-reload && systemctl enable caddy-naive && systemctl restart caddy-naive"
            )
            if code2 != 0:
                return False, f"Caddy service failed to start: {err2}"

            # Verify caddy-naive really started — do NOT trust exit code alone
            _, svc_out, _ = ssh.exec("systemctl is-active caddy-naive 2>/dev/null || echo inactive")
            if svc_out.strip() not in ("active", "activating"):
                _, journal, _ = ssh.exec("journalctl -u caddy-naive -n 20 --no-pager 2>/dev/null || echo no_journal")
                return False, f"caddy-naive started but status={svc_out.strip()}. Journal: {journal[:400]}"
            _log("  caddy-naive.service запущен и включён в автозапуск")

        # ── Шаг 4 (CASCADE only): Xray на RU — VLESS inbound + outbound на EU ──
        if is_cascade:
            _log(f"Шаг 4: Настройка Xray на RU сервере для CASCADE")

            # Находим VLESS+Reality подключение на EU сервере (используем первое активное)
            from app.models.connection import Protocol as P
            eu_vless = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.protocol == P.VLESS_REALITY,
                Connection.is_active == True,
                Connection.reality_public_key.isnot(None),
            ).first()

            eu_outbound = None
            if eu_vless and eu_vless.reality_public_key and eu_vless.reality_public_key != "auto-generated-run-xray-x25519":
                eu_outbound = gen_xray_outbound_to_eu(
                    eu_ip=server.ip,
                    eu_port=eu_vless.port,
                    eu_uuid=eu_vless.uuid,
                    eu_public_key=eu_vless.reality_public_key,
                    eu_short_id=eu_vless.reality_short_id or "",
                    eu_server_name=eu_vless.reality_server_name or "www.microsoft.com",
                )
                _log(f"  EU outbound: {server.ip}:{eu_vless.port} (VLESS+Reality)")
            else:
                _log(f"  ⚠ Нет активного VLESS+Reality на EU — outbound не настроен, трафик через direct")

            # Собираем все существующие inbound'ы RU сервера (AWG, VLESS на RU если есть)
            existing_ru_inbounds = []
            ru_vless_conns = db.query(Connection).filter(
                Connection.server_id == ru_server.id,
                Connection.protocol == P.VLESS_REALITY,
                Connection.is_active == True,
                Connection.uuid.isnot(None),
                Connection.reality_private_key.isnot(None),
            ).all()
            for c in ru_vless_conns:
                if c.reality_public_key and c.reality_public_key != "auto-generated-run-xray-x25519":
                    existing_ru_inbounds.append(
                        gen_xray_vless_reality_inbound(
                            port=c.port,
                            uuid_str=c.uuid,
                            public_key=c.reality_public_key,
                            private_key=c.reality_private_key,
                            short_id=c.reality_short_id or "",
                            server_name=c.reality_server_name or "www.microsoft.com",
                        )
                    )

            # WARP fallback — проверяем активен ли warp-svc на RU
            warp_outbound = None
            with SSHClient(ru_server) as ssh_ru:
                code_w, out_w, _ = ssh_ru.exec("systemctl is-active warp-svc 2>/dev/null || echo inactive")
                if out_w.strip() == "active":
                    warp_outbound = gen_xray_warp_outbound()
                    _log("  WARP fallback: активен ✅")
                else:
                    _log("  WARP fallback: не активен (warp-svc не запущен)")

                # Строим и загружаем Xray конфиг на RU
                ru_config = build_ru_xray_config(
                    inbounds=existing_ru_inbounds,
                    eu_outbound=eu_outbound,
                    warp_outbound=warp_outbound,
                )
                ssh_ru.upload_file(ru_config, "/usr/local/etc/xray/config.json")
                code3, _, err3 = ssh_ru.exec("systemctl reload xray 2>/dev/null || systemctl restart xray")
                if code3 != 0:
                    _log(f"  ⚠ Xray reload вернул ошибку: {err3[:200]}")
                else:
                    _log(f"  Xray на RU перезагружен с {len(existing_ru_inbounds)} inbound(s) + EU outbound")

        # ── Шаг 5: Обновление поддомена в БД ────────────────────────────────
        _log("Шаг 5: Обновление статуса поддомена в БД")
        subdomain_type = "naiveproxy_ru" if is_cascade else "naiveproxy_eu"
        from app.models.domain import Subdomain
        sub = db.query(Subdomain).filter(Subdomain.subdomain_type == subdomain_type).first()
        if sub:
            sub.status = "active"
            sub.status_message = f"NaiveProxy {'cascade' if is_cascade else 'direct'} — порт {port}"
            db.commit()
            _log(f"  Поддомен {sub.full_name} → active")
        else:
            _log(f"  Поддомен типа '{subdomain_type}' не найден в БД")

        # ── Шаг 6: Сохранение client_link и config_text ─────────────────────
        client_cfg = build_naiveproxy_client_config(domain, port, password)
        connection.config_json  = client_cfg
        connection.config_text  = client_cfg
        connection.np_domain    = domain
        # Tag format: "FIN 1 | NaiveProxy (direct)" — same style as VLESS
        _srv_name_np = server.display_name or server.name or server.ip
        _ctype_np = connection.connection_type.value if connection.connection_type else "direct"
        _np_tag = f"{_srv_name_np} | NaiveProxy ({_ctype_np})"
        connection.client_link  = f"https://admin:{password}@{domain}:{port}#{_np_tag}"
        db.commit()

        _log(f"✅ NaiveProxy {'CASCADE' if is_cascade else 'DIRECT'} задеплоен. client_link={connection.client_link}")
        return True, f"NaiveProxy {'cascade' if is_cascade else 'direct'} deployed → {domain}:{port}"

    except Exception as e:
        logger.error(f"NaiveProxy deploy error: {e}")
        _log(f"❌ Исключение: {e}")
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
    ru_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """Install AmneziaWG and deploy a WireGuard peer on server."""
    try:
        with SSHClient(server) as ssh:
            # Prepare server: ip_forward, DNS, UFW port (AWG uses UDP)
            _ensure_server_ready(ssh, connection.port, proto="udp")

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

            # Save to connection
            connection.wg_private_key = server_priv
            connection.wg_public_key = server_pub
            connection.wg_preshared_key = psk
            connection.wg_client_private_key = client_priv
            connection.wg_client_public_key = client_pub
            connection.wg_client_ip = client_ip
            connection.awg_junk_packet_count = connection.awg_junk_packet_count or 4
            connection.awg_junk_packet_min_size = connection.awg_junk_packet_min_size or 40
            connection.awg_junk_packet_max_size = connection.awg_junk_packet_max_size or 70

            # Build peer list: current connection first, then all OTHER active AWG connections.
            # Current connection is excluded from the DB query to avoid duplicate peers
            # (its keys were just generated and not yet committed).
            clients_list = [{
                "pub_key": client_pub,
                "preshared_key": psk,
                "client_ip": client_ip,
            }]

            other_awg = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.id != connection.id,
                Connection.protocol == Protocol.AMNEZIA_WG,
                Connection.is_active == True,
                Connection.wg_client_public_key.isnot(None),
            ).all()

            for c in other_awg:
                if c.wg_client_public_key and c.wg_client_ip:
                    clients_list.append({
                        "pub_key": c.wg_client_public_key,
                        "preshared_key": c.wg_preshared_key or "",
                        "client_ip": c.wg_client_ip,
                    })

            # Определяем реальное имя сетевого интерфейса (eth0, ens3, enp0s3 и т.п.)
            _, net_iface_out, _ = ssh.exec(
                "ip route | grep '^default' | awk '{print $5}' | head -1"
            )
            net_iface = net_iface_out.strip() or "eth0"

            # Generate server config
            server_conf = gen_awg_server_config(
                server_private_key=server_priv,
                listen_port=connection.port,
                net_interface=net_iface,
                clients=clients_list,
                junk_packet_count=connection.awg_junk_packet_count,
                junk_packet_min_size=connection.awg_junk_packet_min_size,
                junk_packet_max_size=connection.awg_junk_packet_max_size,
            )

            # Определяем имя интерфейса по номеру подключения (direct=wg0, cascade=wg1, etc.)
            existing_awg_count = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.protocol == Protocol.AMNEZIA_WG,
                Connection.id != connection.id,
                Connection.is_active == True,
            ).count()
            iface_name = f"wg{existing_awg_count}"

            conf_path = f"/etc/amnezia/amneziawg/{iface_name}.conf"

            # mkdir BEFORE upload
            ssh.exec(f"mkdir -p /etc/amnezia/amneziawg")
            ssh.upload_file(server_conf, conf_path)

            # Запускаем через systemd (если интерфейс уже существует — сначала down)
            svc = f"awg-quick@{iface_name}"
            ssh.exec(f"systemctl enable {svc} 2>/dev/null || true")
            ssh.exec(f"awg-quick down {iface_name} 2>/dev/null || true")
            ssh.exec(f"ip link delete {iface_name} 2>/dev/null || true")
            code3, out3, err3 = ssh.exec(f"systemctl start {svc} 2>&1 || awg-quick up {iface_name} 2>&1")

            # Verify interface actually came up
            _, iface_out, _ = ssh.exec(f"ip link show {iface_name} 2>/dev/null || echo NO_INTERFACE")
            if "NO_INTERFACE" in iface_out or iface_name not in iface_out:
                return False, f"AWG interface {iface_name} did not come up. stderr={err3[:300]}"

            # Generate client config
            _srv_name = server.display_name or server.name or server.ip
            _ctype = connection.connection_type.value if connection.connection_type else "direct"
            _awg_tag = f"{_srv_name} | AWG ({_ctype})"
            client_conf = gen_awg_client_config(
                client_private_key=client_priv,
                client_ip=client_ip,
                server_public_key=server_pub,
                preshared_key=psk,
                server_endpoint=f"{server.ip}:{connection.port}",
                junk_packet_count=connection.awg_junk_packet_count,
                junk_packet_min_size=connection.awg_junk_packet_min_size,
                junk_packet_max_size=connection.awg_junk_packet_max_size,
                name=_awg_tag,
            )
            connection.config_json = client_conf
            connection.config_text = client_conf
            # Tag format: "FIN 1 | AWG (direct)" — same style as VLESS
            connection.client_link = f"awg://peer?pub={server_pub}&endpoint={server.ip}:{connection.port}#{_awg_tag}"
            db.commit()

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


def restart_single_service(server: Server, service: str) -> Tuple[bool, str]:
    """Restart a single systemd service on a server."""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(f"systemctl restart {service} 2>&1 || echo 'not found'", timeout=30)
            if code != 0:
                return False, f"Failed to restart {service}: {err or out}"
            # Check active status
            code2, status_out, _ = ssh.exec(f"systemctl is-active {service} 2>/dev/null || echo inactive")
            status = status_out.strip()
            if status in ("active", "activating"):
                return True, f"{service} restarted successfully (status: {status})"
            else:
                return False, f"{service} restart issued but status is: {status}"
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

        config_str = build_eu_xray_config(inbounds)

        with SSHClient(server) as ssh:
            ssh.upload_file(config_str, "/usr/local/etc/xray/config.json")
            ssh.exec("systemctl reload xray || systemctl restart xray")

        return True, "Connection removed from server"
    except Exception as e:
        return False, str(e)
