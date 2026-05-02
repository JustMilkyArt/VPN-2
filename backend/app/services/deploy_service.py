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
# STRUCTURED LOGGING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _step_log(connection: Connection, db: Session, step: int, status: str, msg: str) -> None:
    """
    Append a structured step line to connection.setup_log.
    Format: [STEP:N:status:message]
    status: running | ok | error | skip
    """
    cur = connection.setup_log or ""
    connection.setup_log = cur + f"[STEP:{step}:{status}:{msg}]\n"
    try:
        db.commit()
    except Exception:
        db.rollback()


def _raw_log(connection: Connection, db: Session, msg: str) -> None:
    """Append a plain (non-step) log line."""
    cur = connection.setup_log or ""
    connection.setup_log = cur + msg + "\n"
    try:
        db.commit()
    except Exception:
        db.rollback()

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


# ─── DPKG lock helper (used before every apt-get) ────────────────────────────
_WAIT_DPKG = """
# Wait for dpkg lock to be released (unattended-upgrades / cloud-init etc.)
_wait_dpkg() {
    local i=0
    while flock -n /var/lib/dpkg/lock-frontend true 2>/dev/null; [ $? -ne 0 ] ||           flock -n /var/lib/dpkg/lock true 2>/dev/null; [ $? -ne 0 ]; do
        true  # lock is free, break
        break
    done
    while ! flock -n /var/lib/dpkg/lock-frontend true 2>/dev/null ||           ! flock -n /var/lib/dpkg/lock true 2>/dev/null; do
        i=$((i+1))
        [ $i -gt 60 ] && { echo "[!] dpkg lock timeout after 5 min"; return 1; }
        echo "[*] Waiting for dpkg lock ($i/60)..."
        sleep 5
    done
    return 0
}
"""

AWG_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing AmneziaWG..."

# Wait for dpkg lock
_wait_dpkg() {
    local i=0
    while ! flock -n /var/lib/dpkg/lock-frontend /bin/true 2>/dev/null ||           ! flock -n /var/lib/dpkg/lock /bin/true 2>/dev/null; do
        i=$((i+1))
        [ $i -gt 60 ] && { echo "[!] dpkg lock timeout"; exit 1; }
        echo "[*] Waiting for dpkg lock ($i/60)..."
        sleep 5
    done
}
_wait_dpkg

# Kill any stuck apt/dpkg processes that hold the lock
kill $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
kill $(lsof /var/lib/dpkg/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
dpkg --configure -a 2>/dev/null || true

DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq software-properties-common

# Add AmneziaWG PPA (Ubuntu) or fall back to real binaries from GitHub
AWG_VIA_PPA=0
if DEBIAN_FRONTEND=noninteractive add-apt-repository -y ppa:amnezia/ppa 2>/dev/null; then
    if DEBIAN_FRONTEND=noninteractive apt-get update -qq && \
       DEBIAN_FRONTEND=noninteractive apt-get install -y -qq amneziawg amneziawg-tools; then
        AWG_VIA_PPA=1
    fi
fi

if [ "$AWG_VIA_PPA" = "0" ]; then
    echo "[!] PPA failed — downloading real awg/awg-quick binaries from GitHub..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard wireguard-tools unzip curl 2>/dev/null || true

    # Download real amneziawg-tools binaries (contains actual awg and awg-quick)
    AWG_TOOLS_URL="https://github.com/amnezia-vpn/amneziawg-tools/releases/latest/download/ubuntu-22.04-amneziawg-tools.zip"
    mkdir -p /tmp/awg_tools
    if curl -fsSL "$AWG_TOOLS_URL" -o /tmp/awg_tools/awg-tools.zip 2>/dev/null; then
        unzip -o /tmp/awg_tools/awg-tools.zip -d /tmp/awg_tools/ 2>/dev/null || true
        AWG_BIN=$(find /tmp/awg_tools -name "awg" -type f | head -1)
        AWG_QUICK_BIN=$(find /tmp/awg_tools -name "awg-quick" -type f | head -1)
        if [ -n "$AWG_BIN" ]; then
            cp "$AWG_BIN" /usr/local/bin/awg
            chmod +x /usr/local/bin/awg
            echo "[+] awg binary installed from zip"
        fi
        if [ -n "$AWG_QUICK_BIN" ]; then
            cp "$AWG_QUICK_BIN" /usr/local/bin/awg-quick
            chmod +x /usr/local/bin/awg-quick
            echo "[+] awg-quick binary installed from zip"
        else
            # awg-quick is a shell script — download separately
            AWG_QUICK_URL="https://raw.githubusercontent.com/amnezia-vpn/amneziawg-tools/master/src/awg-quick/linux.bash"
            curl -fsSL "$AWG_QUICK_URL" -o /usr/local/bin/awg-quick 2>/dev/null && \
                chmod +x /usr/local/bin/awg-quick && echo "[+] awg-quick script installed from source"
        fi
        rm -rf /tmp/awg_tools
    fi

    # Download DKMS kernel module for amneziawg
    AWG_DKMS_VER=$(curl -fsSL https://api.github.com/repos/amnezia-vpn/amneziawg-linux-kernel-module/releases/latest 2>/dev/null | grep '"tag_name"' | head -1 | cut -d'"' -f4)
    if [ -n "$AWG_DKMS_VER" ]; then
        DKMS_URL="https://github.com/amnezia-vpn/amneziawg-linux-kernel-module/releases/download/${AWG_DKMS_VER}/amneziawg-dkms_${AWG_DKMS_VER#v}-1_all.deb"
        if curl -fsSL "$DKMS_URL" -o /tmp/awg-dkms.deb 2>/dev/null; then
            DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/awg-dkms.deb 2>/dev/null || true
            rm -f /tmp/awg-dkms.deb
            echo "[+] amneziawg DKMS module installed"
        fi
    fi
    modprobe amneziawg 2>/dev/null || modprobe wireguard 2>/dev/null || true
fi

# Enable IP forwarding
grep -q 'net.ipv4.ip_forward=1' /etc/sysctl.conf || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
grep -q 'net.ipv6.conf.all.forwarding=1' /etc/sysctl.conf || echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p 2>/dev/null || true

echo "[+] AmneziaWG installed"
"""


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

# Wait for dpkg lock (unattended-upgrades, cloud-init, etc.)
_wait_dpkg() {
    local i=0
    while ! flock -n /var/lib/dpkg/lock-frontend /bin/true 2>/dev/null ||           ! flock -n /var/lib/dpkg/lock /bin/true 2>/dev/null; do
        i=$((i+1))
        [ $i -gt 60 ] && { echo "[!] dpkg lock timeout"; exit 1; }
        echo "[*] Waiting for dpkg lock ($i/60)..."
        sleep 5
    done
}
_wait_dpkg
kill $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
kill $(lsof /var/lib/dpkg/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
dpkg --configure -a 2>/dev/null || true

DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl tar

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



# ─────────────────────────────────────────────────────────────────────────────
# VLESS+Reality DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

def deploy_vless_reality_connection(
    db: Session,
    connection: Connection,
    server: Server,
    exit_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """Deploy VLESS+Reality connection on server.
    Steps:
      1 - Подключение и подготовка сервера
      2 - Проверка / установка Xray
      3 - Генерация Reality keypair
      4 - Сборка Xray конфига
      5 - Перезапуск Xray
      6 - Сохранение client link
    """
    S = lambda n, st, m: _step_log(connection, db, n, st, m)
    try:
        S(1, "running", "Подключение к серверу")
        with SSHClient(server) as ssh:
            _ensure_server_ready(ssh, connection.port, proto="tcp")
            S(1, "ok", f"Сервер {server.ip} готов, порт {connection.port}/tcp открыт")

            # Step 2: Check / install Xray
            S(2, "running", "Проверка Xray")
            code_x, out_x, _ = ssh.exec("xray version 2>/dev/null | head -1 || echo NOT_INSTALLED")
            if "NOT_INSTALLED" in out_x or not out_x.strip():
                S(2, "running", "Xray не найден — устанавливаю...")
                code_xi, _, err_xi = ssh.exec(XRAY_INSTALL_SCRIPT, timeout=300)
                if code_xi != 0:
                    S(2, "error", f"Установка Xray провалилась: {err_xi[:200]}")
                    return False, f"Xray install failed: {err_xi}"
                S(2, "ok", "Xray установлен")
            else:
                S(2, "ok", f"Xray уже установлен ({out_x.strip()[:50]})")

            # Step 3: Generate Reality keypair
            S(3, "running", "Генерация Reality keypair (xray x25519)")
            code, key_out, _ = ssh.exec("xray x25519", timeout=30)
            if code != 0:
                import subprocess
                result = subprocess.run(["xray", "x25519"], capture_output=True, text=True)
                key_out = result.stdout

            private_key = public_key = None
            for line in key_out.splitlines():
                line = line.strip()
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
                S(3, "error", "xray x25519 вернул неожиданный формат")
                return False, "Не удалось сгенерировать Reality keypair"

            short_id = generate_short_id(16)
            connection.reality_private_key = private_key
            connection.reality_public_key  = public_key
            connection.reality_short_id    = short_id
            S(3, "ok", f"Reality keypair готов (short_id={short_id[:8]}...)")

            # Step 4: Build Xray config
            S(4, "running", "Сборка Xray конфига")
            all_connections = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.is_active == True,
                Connection.protocol == Protocol.VLESS_REALITY
            ).all()

            inbounds = []
            for conn in all_connections:
                if conn.uuid and conn.reality_private_key:
                    inbounds.append(gen_xray_vless_reality_inbound(
                        port=conn.port,
                        uuid_str=conn.uuid,
                        public_key=conn.reality_public_key or "",
                        private_key=conn.reality_private_key or "",
                        short_id=conn.reality_short_id or "",
                        server_name=conn.reality_server_name or "www.microsoft.com"
                    ))

            current_ids = {conn.id for conn in all_connections}
            if connection.id not in current_ids:
                inbounds.append(gen_xray_vless_reality_inbound(
                    port=connection.port,
                    uuid_str=connection.uuid,
                    public_key=public_key,
                    private_key=private_key,
                    short_id=short_id,
                    server_name=connection.reality_server_name or "www.microsoft.com"
                ))

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

            # WARP: check if warp-svc is active on this server and add outbound
            warp_outbound = None
            _, warp_status, _ = ssh.exec("systemctl is-active warp-svc 2>/dev/null || echo inactive")
            if warp_status.strip() == "active":
                warp_outbound = gen_xray_warp_outbound()
                _raw_log(connection, db, "  WARP fallback: активен — добавлен warp outbound")
            else:
                _raw_log(connection, db, "  WARP fallback: не активен (warp-svc не запущен)")

            if server.role == ServerRole.RU:
                config_str = build_ru_xray_config(inbounds, eu_outbound=eu_outbound, warp_outbound=warp_outbound)
            else:
                config_str = build_eu_xray_config(inbounds)

            mode = "CASCADE" if is_cascade else "DIRECT"
            if is_cascade and exit_server:
                _raw_log(connection, db, f"  CASCADE: RU={server.ip} → EU={exit_server.ip} (VLESS+Reality outbound)")
            else:
                _raw_log(connection, db, f"  DIRECT: трафик выходит напрямую через {server.ip}")
            S(4, "ok", f"Конфиг собран: {len(inbounds)} inbound(s), режим {mode}")

            # Step 5: Upload and reload Xray
            S(5, "running", "Загрузка конфига и перезапуск Xray")
            ssh.upload_file(config_str, "/usr/local/etc/xray/config.json")
            code2, _, err2 = ssh.exec("systemctl reload xray 2>/dev/null || systemctl restart xray 2>&1")
            if code2 != 0:
                S(5, "error", f"Xray reload провалился: {err2[:150]}")
                return False, f"Xray reload failed: {err2}"

            # 5a: verify xray service is actually running
            _, xray_active, _ = ssh.exec("systemctl is-active xray 2>/dev/null || echo unknown")
            xray_active = xray_active.strip()
            if xray_active not in ("active", "activating"):
                _, xray_journal, _ = ssh.exec("journalctl -u xray -n 15 --no-pager 2>/dev/null || echo no_journal")
                S(5, "error", f"xray.service статус={xray_active}: {xray_journal[:300]}")
                return False, f"xray not running after reload (status={xray_active})"

            # 5b: verify xray is listening on the expected TCP port
            port_str = str(connection.port)
            _, ss_out, _ = ssh.exec(f"ss -tlnp 2>/dev/null | grep ':{port_str}' || echo NOT_LISTENING")
            if "NOT_LISTENING" in ss_out or port_str not in ss_out:
                # non-fatal: log warning but continue (port may appear with tiny delay)
                _raw_log(connection, db, f"  WARN: ss -tlnp не показал :{port_str} сразу после старта")
            else:
                _raw_log(connection, db, f"  OK: TCP порт {port_str} слушается (ss confirm)")
            S(5, "ok", f"Xray активен (статус={xray_active}), порт {port_str}/tcp открыт")

            # Step 6: Save client link
            S(6, "running", "Генерация и сохранение client link")
            _ctype_str = connection.connection_type if isinstance(connection.connection_type, str) else (connection.connection_type.value if connection.connection_type else "direct")
            connection.client_link = gen_vless_reality_client_link(
                server_ip=server.ip,
                port=connection.port,
                uuid_str=connection.uuid,
                public_key=public_key,
                short_id=short_id,
                server_name=connection.reality_server_name or "www.microsoft.com",
                server_flag=getattr(server, 'flag_emoji', '') or '',
                server_display_name=getattr(server, 'display_name', '') or server.name or '',
                connection_type=_ctype_str,
            )
            connection.config_json = config_str
            db.commit()
            S(6, "ok", "VLESS+Reality задеплоен успешно ✅")
            return True, "VLESS+Reality deployed"

    except Exception as e:
        logger.error(f"VLESS+Reality deploy error: {e}")
        _step_log(connection, db, 0, "error", f"Исключение: {e}")
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# NaiveProxy DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

def deploy_naiveproxy_connection(
    db: Session,
    connection: Connection,
    server: Server,
    ru_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """
    Deploy NaiveProxy connection.
    Steps:
      1 - Определение режима (DIRECT/CASCADE) и целевого сервера
      2 - Установка caddy-naive
      3 - Генерация и загрузка Caddyfile
      4 - Запуск systemd сервиса caddy-naive
      5 - Настройка Xray на RU (CASCADE) / пропуск (DIRECT)
      6 - Обновление поддомена в БД
      7 - Сохранение client link
    """
    S = lambda n, st, m: _step_log(connection, db, n, st, m)
    try:
        password = connection.password
        port     = connection.port

        # Step 1: Determine mode and target
        if is_cascade:
            if not ru_server:
                S(1, "error", "CASCADE: ru_server не передан")
                return False, "CASCADE: ru_server не передан"
            target_server = ru_server
            domain = ru_server.domain or ru_server.ip
            S(1, "ok", f"Режим CASCADE → Caddy-naive на RU сервере ({domain})")
        else:
            target_server = server
            domain = server.domain or server.ip
            S(1, "ok", f"Режим DIRECT → Caddy-naive на EU сервере ({domain})")

        # Step 2: Install caddy-naive
        S(2, "running", f"Установка caddy-naive на {target_server.name} ({target_server.ip})")
        with SSHClient(target_server) as ssh:
            _ensure_server_ready(ssh, port, proto="tcp")
            code, out, err = ssh.exec(_CADDY_INSTALL_SCRIPT, timeout=300)
            if code != 0:
                S(2, "error", f"caddy-naive install failed: {(err or out)[:200]}")
                return False, f"caddy-naive install failed: {err or out}"
            version_line = [l for l in out.splitlines() if "caddy-naive installed" in l or "already installed" in l]
            S(2, "ok", f"caddy-naive: {version_line[-1] if version_line else 'установлен'}")

            # Step 3: Generate and upload Caddyfile
            S(3, "running", f"Генерация Caddyfile (домен={domain}, порт={port})")
            caddy_config = build_naiveproxy_caddy_config(domain, password, port)
            ssh.upload_file(caddy_config, "/etc/caddy/Caddyfile")
            S(3, "ok", "Caddyfile загружен → /etc/caddy/Caddyfile")

            # Step 4: Start caddy-naive systemd service
            S(4, "running", "Запуск systemd сервиса caddy-naive")
            ssh.upload_file(_CADDY_SERVICE, "/etc/systemd/system/caddy-naive.service")
            code2, _, err2 = ssh.exec(
                "systemctl daemon-reload && systemctl enable caddy-naive && systemctl restart caddy-naive"
            )
            if code2 != 0:
                S(4, "error", f"Сервис не запустился: {err2[:200]}")
                return False, f"Caddy service failed to start: {err2}"

            _, svc_out, _ = ssh.exec("systemctl is-active caddy-naive 2>/dev/null || echo inactive")
            if svc_out.strip() not in ("active", "activating"):
                _, journal, _ = ssh.exec("journalctl -u caddy-naive -n 20 --no-pager 2>/dev/null || echo no_journal")
                S(4, "error", f"caddy-naive статус={svc_out.strip()}: {journal[:250]}")
                return False, f"caddy-naive status={svc_out.strip()}. Journal: {journal[:400]}"
            S(4, "ok", "caddy-naive.service активен и добавлен в автозапуск")

            # 4a: TLS certificate check — confirm Let's Encrypt issued (not self-signed)
            _raw_log(connection, db, f"  Проверка TLS сертификата {domain}:{port} ...")
            _, tls_out, _ = ssh.exec(
                f"curl -sI --max-time 10 --connect-timeout 8 "
                f"https://{domain}:{port}/ 2>&1 | head -5 || echo TLS_CHECK_FAILED"
            )
            if "TLS_CHECK_FAILED" in tls_out or "curl" not in tls_out.lower() and "HTTP" not in tls_out:
                _raw_log(connection, db,
                  f"  WARN: TLS проверка не дала HTTP ответа "
                  f"(сервис только запустился, сертификат ещё получается): {tls_out[:150]}")
            else:
                first_line = tls_out.splitlines()[0] if tls_out.strip() else "—"
                _raw_log(connection, db, f"  TLS OK: {first_line.strip()}")

            # 4b: functional proxy test — curl through naive proxy from server
            _raw_log(connection, db, f"  Функциональный тест: curl через naive proxy → 1.1.1.1 ...")
            _, proxy_out, _ = ssh.exec(
                f"curl -s --max-time 15 --connect-timeout 10 "
                f"-x https://admin:{password}@{domain}:{port} "
                f"https://1.1.1.1/ -o /dev/null -w '%{{http_code}}' 2>&1 || echo PROXY_TEST_FAILED"
            )
            proxy_out = proxy_out.strip()
            if proxy_out in ("200", "301", "302"):
                _raw_log(connection, db, f"  PROXY OK: HTTP {proxy_out} — NaiveProxy работает")
            elif "PROXY_TEST_FAILED" in proxy_out or proxy_out == "":
                _raw_log(connection, db,
                  "  WARN: Прокси-тест упал (curl не смог выполнить запрос). "
                  "Возможно, сертификат ещё получается или порт заблокирован.")
            else:
                _raw_log(connection, db,
                  f"  WARN: Прокси вернул HTTP {proxy_out} (ожидали 200/301/302). "
                  f"Может быть нормальным если 1.1.1.1 редиректит.")

        # Step 5: CASCADE — configure Xray on RU
        if is_cascade:
            S(5, "running",
              f"CASCADE: настройка Xray на RU сервере ({ru_server.ip}) "
              f"для проброса трафика → EU ({server.ip})")
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
                    eu_ip=server.ip, eu_port=eu_vless.port, eu_uuid=eu_vless.uuid,
                    eu_public_key=eu_vless.reality_public_key,
                    eu_short_id=eu_vless.reality_short_id or "",
                    eu_server_name=eu_vless.reality_server_name or "www.microsoft.com",
                )
                _raw_log(connection, db, f"  EU outbound: {server.ip}:{eu_vless.port} (VLESS+Reality)")
            else:
                _raw_log(connection, db, "  Нет активного VLESS+Reality на EU — трафик через direct")

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
                    existing_ru_inbounds.append(gen_xray_vless_reality_inbound(
                        port=c.port, uuid_str=c.uuid, public_key=c.reality_public_key,
                        private_key=c.reality_private_key, short_id=c.reality_short_id or "",
                        server_name=c.reality_server_name or "www.microsoft.com",
                    ))

            warp_outbound = None
            with SSHClient(ru_server) as ssh_ru:
                _, out_w, _ = ssh_ru.exec("systemctl is-active warp-svc 2>/dev/null || echo inactive")
                if out_w.strip() == "active":
                    warp_outbound = gen_xray_warp_outbound()
                    _raw_log(connection, db, "  WARP fallback: активен")
                else:
                    _raw_log(connection, db, "  WARP fallback: не активен")

                ru_config = build_ru_xray_config(
                    inbounds=existing_ru_inbounds, eu_outbound=eu_outbound, warp_outbound=warp_outbound,
                )
                ssh_ru.upload_file(ru_config, "/usr/local/etc/xray/config.json")
                code3, _, err3 = ssh_ru.exec("systemctl reload xray 2>/dev/null || systemctl restart xray")
                if code3 != 0:
                    S(5, "error", f"Xray reload на RU провалился: {err3[:150]}")
                else:
                    # verify RU xray is active
                    _, ru_xray_status, _ = ssh_ru.exec("systemctl is-active xray 2>/dev/null || echo unknown")
                    _raw_log(connection, db,
                      f"  CASCADE OK: RU Xray статус={ru_xray_status.strip()}, "
                      f"{len(existing_ru_inbounds)} inbound(s), "
                      f"EU outbound={'есть' if eu_outbound else 'нет (direct)'}, "
                      f"WARP={'есть' if warp_outbound else 'нет'}")
                    S(5, "ok",
                      f"CASCADE: Xray на RU ({ru_server.ip}) перезагружен "
                      f"→ проброс на EU ({server.ip})")
        else:
            S(5, "skip", "Xray на RU не нужен (режим DIRECT)")

        # Step 6: Update subdomain in DB
        S(6, "running", "Обновление статуса поддомена в БД")
        subdomain_type = "naiveproxy_ru" if is_cascade else "naiveproxy_eu"
        from app.models.domain import Subdomain
        sub = db.query(Subdomain).filter(Subdomain.subdomain_type == subdomain_type).first()
        if sub:
            sub.status = "active"
            sub.status_message = f"NaiveProxy {'cascade' if is_cascade else 'direct'} — порт {port}"
            db.commit()
            S(6, "ok", f"Поддомен {sub.full_name} → active")
        else:
            S(6, "skip", f"Поддомен '{subdomain_type}' не найден в БД")

        # Step 7: Save client link
        S(7, "running", "Сохранение client link")
        client_cfg = build_naiveproxy_client_config(domain, port, password)
        connection.config_json = client_cfg
        connection.config_text = client_cfg
        connection.np_domain   = domain
        _srv_name = server.display_name or server.name or server.ip
        _ctype    = connection.connection_type if isinstance(connection.connection_type, str) \
            else (connection.connection_type.value if connection.connection_type else "direct")
        connection.client_link = f"https://admin:{password}@{domain}:{port}#{_srv_name} | NaiveProxy ({_ctype})"
        db.commit()
        S(7, "ok", f"NaiveProxy {'CASCADE' if is_cascade else 'DIRECT'} задеплоен успешно ✅")
        return True, f"NaiveProxy {'cascade' if is_cascade else 'direct'} deployed → {domain}:{port}"

    except Exception as e:
        logger.error(f"NaiveProxy deploy error: {e}")
        _step_log(connection, db, 0, "error", f"Исключение: {e}")
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# AWG INSTALL HELPERS (kept separate from XRAY/CADDY scripts above)
# ─────────────────────────────────────────────────────────────────────────────

def _wg_genkey_on_server(ssh) -> Tuple[str, str]:
    """Generate WireGuard keypair on server, return (private, public)."""
    _, priv, _ = ssh.exec("awg genkey 2>/dev/null || wg genkey")
    priv = priv.strip()
    _, pub, _ = ssh.exec(f"echo '{priv}' | awg pubkey 2>/dev/null || echo '{priv}' | wg pubkey")
    return priv, pub.strip()


def _wg_preshared_on_server(ssh) -> str:
    """Generate WireGuard preshared key on server."""
    _, psk, _ = ssh.exec("awg genpsk 2>/dev/null || wg genpsk")
    return psk.strip()


def _get_next_client_ip(db: Session, server_id: int) -> str:
    """Get next available client IP in 10.8.0.x range."""
    used = db.query(Connection.wg_client_ip).filter(
        Connection.server_id == server_id,
        Connection.wg_client_ip.isnot(None),
    ).all()
    used_ips = {r[0] for r in used if r[0]}
    for i in range(2, 255):
        ip = f"10.8.0.{i}"
        if ip not in used_ips:
            return ip
    raise RuntimeError("No free IP addresses in 10.8.0.0/24")


# ─────────────────────────────────────────────────────────────────────────────
# AmneziaWG DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

def deploy_amnezia_wg_connection(
    db: Session,
    connection: Connection,
    server: Server,
    ru_server: Optional[Server] = None,
    is_cascade: bool = False,
) -> Tuple[bool, str]:
    """Install AmneziaWG and deploy a WireGuard peer on server.
    Steps:
      1 - Подключение и подготовка сервера (UDP)
      2 - Проверка / установка AmneziaWG
      3 - Генерация ключей (сервер + клиент + PSK)
      4 - Сборка серверного конфига wgN.conf
      5 - Запуск awg-quick@wgN
      6 - Верификация интерфейса
      7 - Генерация клиентского конфига и client link
    """
    S = lambda n, st, m: _step_log(connection, db, n, st, m)
    try:
        S(1, "running", f"Подключение к серверу {server.ip} (UDP:{connection.port})")
        with SSHClient(server) as ssh:
            _ensure_server_ready(ssh, connection.port, proto="udp")
            S(1, "ok", f"Сервер {server.ip} готов, UDP порт {connection.port} открыт")

            # Step 2: Check / install AWG
            S(2, "running", "Проверка AmneziaWG")
            _, check_out, _ = ssh.exec(
                "which awg 2>/dev/null && echo AWG_OK || "
                "(which wg 2>/dev/null && echo WG_OK || echo NOT_FOUND)"
            )
            if "NOT_FOUND" in check_out:
                S(2, "running", "AmneziaWG не найден — устанавливаю...")
                code2, _, err2 = ssh.exec(AWG_INSTALL_SCRIPT, timeout=300)
                if code2 != 0:
                    S(2, "error", f"Установка провалилась: {err2[:200]}")
                    return False, f"AmneziaWG install failed: {err2}"
                S(2, "ok", "AmneziaWG установлен")
            elif "AWG_OK" in check_out:
                S(2, "ok", "AmneziaWG уже установлен (awg)")
            else:
                S(2, "ok", "WireGuard установлен (wg, AWG-compatible)")

            # Step 3: Generate keypairs
            S(3, "running", "Генерация ключей (сервер + клиент + PSK)")
            existing_server_conn = db.query(Connection).filter(
                Connection.server_id == server.id,
                Connection.protocol == Protocol.AMNEZIA_WG,
                Connection.wg_private_key.isnot(None),
                Connection.id != connection.id,
            ).first()

            if existing_server_conn and existing_server_conn.wg_private_key:
                server_priv = existing_server_conn.wg_private_key
                server_pub  = existing_server_conn.wg_public_key
                _raw_log(connection, db, "  Серверный keypair: переиспользован из существующего подключения")
            else:
                server_priv, server_pub = _wg_genkey_on_server(ssh)
                _raw_log(connection, db, "  Серверный keypair: сгенерирован новый")

            client_priv, client_pub = _wg_genkey_on_server(ssh)
            psk       = _wg_preshared_on_server(ssh)
            client_ip = _get_next_client_ip(db, server.id)

            connection.wg_private_key        = server_priv
            connection.wg_public_key         = server_pub
            connection.wg_preshared_key      = psk
            connection.wg_client_private_key = client_priv
            connection.wg_client_public_key  = client_pub
            connection.wg_client_ip          = client_ip
            connection.awg_junk_packet_count    = connection.awg_junk_packet_count    or 4
            connection.awg_junk_packet_min_size = connection.awg_junk_packet_min_size or 40
            connection.awg_junk_packet_max_size = connection.awg_junk_packet_max_size or 70
            S(3, "ok", f"Ключи готовы, client IP назначен: {client_ip}")

            # Step 4: Build server config
            S(4, "running", "Сборка серверного конфига wgN.conf")
            clients_list = [{"pub_key": client_pub, "preshared_key": psk, "client_ip": client_ip}]

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

            _, net_iface_out, _ = ssh.exec(
                "ip route | grep '^default' | awk '{print $5}' | head -1"
            )
            net_iface = net_iface_out.strip() or "eth0"

            server_conf = gen_awg_server_config(
                server_private_key=server_priv,
                listen_port=connection.port,
                net_interface=net_iface,
                clients=clients_list,
                junk_packet_count=connection.awg_junk_packet_count,
                junk_packet_min_size=connection.awg_junk_packet_min_size,
                junk_packet_max_size=connection.awg_junk_packet_max_size,
            )

            # Determine iface name from actual .conf files on server to avoid conflicts
            _, existing_ifaces_out, _ = ssh.exec(
                "ls /etc/amnezia/amneziawg/*.conf 2>/dev/null | "
                "grep -oP 'wg\\d+' | sort -V || echo NONE"
            )
            used_nums = set()
            for part in existing_ifaces_out.split():
                part = part.strip()
                if part.startswith('wg') and part[2:].isdigit():
                    used_nums.add(int(part[2:]))
            iface_num = 0
            while iface_num in used_nums:
                iface_num += 1
            iface_name = f"wg{iface_num}"
            conf_path  = f"/etc/amnezia/amneziawg/{iface_name}.conf"
            _raw_log(connection, db, f"  Интерфейс: {iface_name} (занятые: {sorted(used_nums)})")

            ssh.exec("mkdir -p /etc/amnezia/amneziawg")
            ssh.upload_file(server_conf, conf_path)
            S(4, "ok", f"Конфиг загружен: {conf_path} ({len(clients_list)} peer(s), iface={iface_name}, net={net_iface})")

            # Step 5: Start awg-quick service
            S(5, "running", f"Запуск сервиса awg-quick@{iface_name}")
            svc = f"awg-quick@{iface_name}"

            # Validate config before starting
            _, cat_conf, _ = ssh.exec(f"cat {conf_path} 2>/dev/null | head -30 || echo CONF_MISSING")
            if "CONF_MISSING" in cat_conf or "[Interface]" not in cat_conf:
                S(5, "error", f"Конфиг {conf_path} не найден или пуст")
                return False, f"AWG config missing at {conf_path}"
            _raw_log(connection, db, f"  Config preview: {cat_conf[:200].strip()}")

            # Ensure amneziawg kernel module is loaded
            ssh.exec("modprobe amneziawg 2>/dev/null || modprobe wireguard 2>/dev/null || true")

            # Bring down any existing interface first
            ssh.exec(f"awg-quick down {iface_name} 2>/dev/null || wg-quick down {iface_name} 2>/dev/null || true")
            ssh.exec(f"ip link delete {iface_name} 2>/dev/null || true")
            ssh.exec(f"systemctl stop {svc} 2>/dev/null || true")

            # Enable + start via systemd (preferred), fall back to awg-quick up
            ssh.exec(f"systemctl daemon-reload 2>/dev/null || true")
            ssh.exec(f"systemctl enable {svc} 2>/dev/null || true")
            code3, out3, err3 = ssh.exec(
                f"systemctl start {svc} 2>&1; "
                f"sleep 1; "
                f"systemctl is-active {svc} 2>/dev/null || echo svc_failed"
            )
            svc_active = "svc_failed" not in (out3 or "") and "active" in (out3 or "")

            if not svc_active:
                # Fallback: direct awg-quick up
                _raw_log(connection, db, f"  systemd start failed ({err3[:100]}), trying awg-quick up directly...")
                code3b, out3b, err3b = ssh.exec(
                    f"awg-quick up {conf_path} 2>&1 || wg-quick up {conf_path} 2>&1 || echo AWG_UP_FAILED"
                )
                if "AWG_UP_FAILED" in (out3b or ""):
                    _raw_log(connection, db, f"  awg-quick up also failed: {err3b[:200]}")
                else:
                    _raw_log(connection, db, f"  awg-quick up result: {out3b[:200]}")

            # Step 6: Verify interface
            S(6, "running", f"Верификация интерфейса {iface_name}")
            _, iface_out, _ = ssh.exec(f"ip link show {iface_name} 2>/dev/null || echo NO_INTERFACE")
            if "NO_INTERFACE" in iface_out or iface_name not in iface_out:
                # Last attempt: try with full path
                ssh.exec(f"awg-quick up /etc/amnezia/amneziawg/{iface_name}.conf 2>/dev/null || true")
                import time; time.sleep(2)
                _, iface_out2, _ = ssh.exec(f"ip link show {iface_name} 2>/dev/null || echo NO_INTERFACE")
                if "NO_INTERFACE" in iface_out2 or iface_name not in iface_out2:
                    _, start_err, _ = ssh.exec(
                        f"journalctl -u awg-quick@{iface_name} -n 30 --no-pager 2>/dev/null; "
                        f"echo '---'; "
                        f"cat {conf_path} 2>/dev/null | head -20; "
                        f"echo '---'; "
                        f"ls /etc/amnezia/amneziawg/ 2>/dev/null || echo no_dir"
                    )
                    S(5, "error", f"awg-quick@{iface_name} не запустился")
                    S(6, "error", f"Интерфейс {iface_name} не поднялся. Лог: {start_err[:300]}")
                    return False, f"AWG interface {iface_name} did not come up. log={start_err[:400]}"
                iface_out = iface_out2

            iface_state = "UP" if ("UP" in iface_out or "UNKNOWN" in iface_out) else "unknown"
            S(5, "ok", f"Сервис awg-quick@{iface_name} запущен")
            S(6, "ok", f"Интерфейс {iface_name} активен (state: {iface_state})")

            # 6a: verify UDP port is actually listening
            _, udp_out, _ = ssh.exec(
                f"ss -ulnp 2>/dev/null | grep ':{connection.port}' || echo NOT_LISTENING"
            )
            if "NOT_LISTENING" in udp_out:
                S(6, "error",
                  f"UDP порт {connection.port} НЕ слушается — интерфейс поднят, "
                  f"но AWG не принимает пакеты. Проверь ListenPort в конфиге.")
                return False, f"AWG interface up but UDP {connection.port} not listening"
            _raw_log(connection, db, f"  OK: UDP {connection.port} слушается ({udp_out.strip()[:80]})")

            # 6b: awg show — peer list and handshake status
            _, awg_show, _ = ssh.exec(
                f"awg show {iface_name} 2>/dev/null || echo AWG_SHOW_FAILED"
            )
            if "AWG_SHOW_FAILED" in awg_show:
                _raw_log(connection, db, "  WARN: awg show не сработал (возможно, команда awg недоступна)")
            else:
                lines = [l.strip() for l in awg_show.splitlines() if l.strip()]
                _raw_log(connection, db, "  awg show " + iface_name + ":")
                for l in lines[:15]:          # не более 15 строк в лог
                    _raw_log(connection, db, "    " + l)

            # 6c: NAT / iptables check — PostUp rules must be in place
            _, nat_out, _ = ssh.exec(
                "iptables -t nat -L POSTROUTING -n --line-numbers 2>/dev/null | grep MASQUERADE || echo NO_MASQ"
            )
            if "NO_MASQ" in nat_out:
                S(6, "error",
                  f"MASQUERADE правило не найдено в iptables — клиентский трафик не будет маршрутизироваться. "
                  f"Добавь PostUp/PostDown в {conf_path}")
                # non-fatal: the interface is up, but connectivity will fail
                _raw_log(connection, db,
                  "  WARN: NAT MASQUERADE отсутствует. "
                  "Клиент подключится к интерфейсу, но Интернет работать не будет. "
                  "PostUp/PostDown правила не применились.")
            else:
                _raw_log(connection, db,
                  f"  OK: NAT MASQUERADE присутствует — {nat_out.strip()[:120]}")

            S(6, "ok",
              f"Интерфейс {iface_name} проверен: UDP {connection.port} слушается, "
              f"awg show выполнен, NAT {'OK' if 'NO_MASQ' not in nat_out else 'WARN: нет MASQUERADE'}")

            # Step 7: Generate client config and link
            S(7, "running", "Генерация клиентского конфига и client link")
            _srv_name = server.display_name or server.name or server.ip
            _ctype    = connection.connection_type if isinstance(connection.connection_type, str) \
                else (connection.connection_type.value if connection.connection_type else "direct")
            _awg_tag  = f"{_srv_name} | AWG ({_ctype})"
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
            connection.config_json  = client_conf
            connection.config_text  = client_conf
            connection.client_link  = f"awg://peer?pub={server_pub}&endpoint={server.ip}:{connection.port}#{_awg_tag}"
            db.commit()
            S(7, "ok", f"AmneziaWG задеплоен успешно ✅  endpoint={server.ip}:{connection.port}")
            return True, "AmneziaWG deployed"

    except Exception as e:
        logger.error(f"AmneziaWG deploy error: {e}")
        _step_log(connection, db, 0, "error", f"Исключение: {e}")
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
