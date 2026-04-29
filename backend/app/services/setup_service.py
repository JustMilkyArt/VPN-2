"""
Setup Service — автоматическая настройка сервера при создании.

Шаги:
  1. Проверка подключения
  2. Установка стека (xray, awg, naiveproxy+caddy, warp для RU)
  3. Настройка безопасности (apt upgrade критичных пакетов, fail2ban+ufw одной командой,
     смена пользователя, генерация SSH-ключа, смена пароля, отключение password auth,
     смена порта через systemd-run)
  4. Сбор информации о сервере + запись security flags в БД
  5. Финальная проверка (install и start — раздельно)
"""
import io
import logging
import random
import secrets
import string
import select
import time
from typing import Optional, Tuple

import paramiko
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.server import Server, ServerRole, ServerStatus

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Шифрование чувствительных данных
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    from app.core.config import settings
    key = getattr(settings, "SECRET_KEY", None)
    if not key:
        raise RuntimeError("SECRET_KEY not set")
    import base64, hashlib
    digest = hashlib.sha256(key.encode()).digest()
    b64 = base64.urlsafe_b64encode(digest)
    return Fernet(b64)


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные генераторы
# ─────────────────────────────────────────────────────────────────────────────

def _gen_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and
                any(c.isupper() for c in pwd) and
                any(c.isdigit() for c in pwd)):
            return pwd


def _gen_ssh_port() -> int:
    """Случайный порт в диапазоне 10000–65000 (оптимальный: выше ephemeral ports)."""
    return random.randint(10000, 65000)


def _gen_username() -> str:
    suffix = random.randint(1000, 9999)
    return f"vpnadmin{suffix}"


def _gen_ed25519_keypair() -> Tuple[str, str]:
    """Генерирует пару Ed25519, возвращает (private_pem, public_openssh).
    Совместимо с paramiko 3.x — используем cryptography напрямую.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption
    )
    import base64, struct

    raw_key = Ed25519PrivateKey.generate()
    priv_pem = raw_key.private_bytes(
        Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
    ).decode()
    pub_raw = raw_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    algo = b"ssh-ed25519"
    wire = struct.pack(">I", len(algo)) + algo + struct.pack(">I", len(pub_raw)) + pub_raw
    pub_b64 = base64.b64encode(wire).decode()
    pub_openssh = f"ssh-ed25519 {pub_b64} vpnadmin"
    return priv_pem, pub_openssh


# ─────────────────────────────────────────────────────────────────────────────
# SSH-хелперы
# ─────────────────────────────────────────────────────────────────────────────

def _connect(ip: str, port: int, user: str,
             password: Optional[str] = None,
             private_key_pem: Optional[str] = None,
             timeout: int = 15) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=ip, port=port, username=user,
                  timeout=timeout, banner_timeout=30, auth_timeout=30)
    if private_key_pem:
        try:
            pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(private_key_pem))
        except Exception:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_pem))
        kwargs["pkey"] = pkey
        kwargs["look_for_keys"] = False
        kwargs["allow_agent"] = False
    elif password:
        kwargs["password"] = password
        kwargs["look_for_keys"] = False
        kwargs["allow_agent"] = False
    client.connect(**kwargs)
    return client


def _exec(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> Tuple[int, str, str]:
    """
    Выполняет команду по SSH с жёстким таймаутом через select().
    recv_exit_status() блокируется вечно при зависании процесса — 
    поэтому читаем через select с дедлайном.
    """
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        return -1, "", "SSH transport не активен"

    chan = transport.open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)

    out_chunks = []
    err_chunks = []
    deadline = time.time() + timeout

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            chan.close()
            return -1, "".join(out_chunks), "".join(err_chunks) + f"\n[TIMEOUT after {timeout}s]"

        wait = min(remaining, 2.0)
        r, _, _ = select.select([chan], [], [], wait)

        if chan in r:
            if chan.recv_ready():
                data = chan.recv(65536)
                if data:
                    out_chunks.append(data.decode("utf-8", errors="replace"))
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if data:
                    err_chunks.append(data.decode("utf-8", errors="replace"))

        if chan.exit_status_ready():
            # Дочитываем остатки буфера
            while chan.recv_ready():
                data = chan.recv(65536)
                if data:
                    out_chunks.append(data.decode("utf-8", errors="replace"))
            while chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if data:
                    err_chunks.append(data.decode("utf-8", errors="replace"))
            code = chan.recv_exit_status()
            chan.close()
            return code, "".join(out_chunks), "".join(err_chunks)

    # Недостижимо, но на всякий случай
    return -1, "".join(out_chunks), "".join(err_chunks)


def _s(cmd: str, use_sudo: bool) -> str:
    """Префиксует команду через sudo -n если пользователь не root."""
    if not use_sudo:
        return cmd
    cmd = cmd.strip()
    if cmd.startswith("sudo ") or cmd.startswith("nohup ") or cmd.startswith("echo "):
        return cmd
    return "sudo -n " + cmd


def _se(client: paramiko.SSHClient, cmd: str, use_sudo: bool, timeout: int = 120) -> tuple:
    """_exec + автоматический sudo."""
    return _exec(client, _s(cmd, use_sudo), timeout=timeout)


def _clear_apt_locks(client: paramiko.SSHClient, db, server, use_sudo: bool = False) -> None:
    """Одноразовая очистка dpkg/apt lock в начале шага 2.
    Останавливает unattended-upgrades, ждёт завершения apt/dpkg процессов,
    при необходимости принудительно снимает lock-файлы.
    """
    # Шаг 1: убиваем unattended-upgrades
    _se(client,
        "systemctl stop unattended-upgrades 2>/dev/null || true; "
        "pkill -9 -f unattended-upgrades 2>/dev/null || true; "
        "pkill -9 -f apt-get 2>/dev/null || true; "
        "sleep 2", use_sudo,
        timeout=15)

    # Шаг 2: ждём пока lock-файлы освободятся (до 120 секунд)
    wait_cmd = (
        "for i in $(seq 1 40); do "
        "pgrep -x apt-get >/dev/null 2>&1 || "
        "pgrep -x dpkg    >/dev/null 2>&1 || "
        "pgrep -f unattended-upgrades >/dev/null 2>&1 || "
        "{ echo FREE; break; }; "
        "sleep 3; done"
    )
    _, out, _ = _exec(client, wait_cmd, timeout=130)

    # Шаг 3: принудительно снимаем lock-файлы если всё ещё заняты
    if "FREE" not in out:
        _se(client,
            "rm -f /var/lib/dpkg/lock-frontend "
            "/var/lib/dpkg/lock "
            "/var/cache/apt/archives/lock 2>/dev/null; "
            "dpkg --configure -a 2>/dev/null || true", use_sudo,
            timeout=60)
        _update_setup(db, server,
                      log_line="[2.0] ⚠️ dpkg lock принудительно снят (unattended-upgrades завис)")


# ─────────────────────────────────────────────────────────────────────────────
# Запись прогресса в БД
# ─────────────────────────────────────────────────────────────────────────────

def _update_setup(db: Session, server: Server, *,
                  step: str = None, log_line: str = None,
                  status: str = None, error: str = None):
    if step:
        server.setup_step = step
    if status:
        server.setup_status = status
    if error is not None:
        server.setup_error = error
    if log_line:
        existing = server.setup_log or ""
        server.setup_log = existing + log_line + "\n"
    db.add(server)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Главная функция — запускается в фоне
# ─────────────────────────────────────────────────────────────────────────────

def run_server_setup(server_id: int):
    """Точка входа — запускается как background task."""
    db = SessionLocal()
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            logger.error(f"Setup: server {server_id} not found")
            return
        _run(db, server)
    except Exception as e:
        logger.error(f"Setup crashed for server {server_id}: {e}", exc_info=True)
    finally:
        db.close()


def _run(db: Session, server: Server):
    _update_setup(db, server, status="in_progress", step="step1",
                  log_line="[setup] Начинаем настройку сервера")
    server.status = ServerStatus.SETTING_UP
    db.add(server); db.commit()

    # Текущие credentials (обновляются по ходу)
    cur_ip   = server.ip
    cur_port = server.ssh_port or 22
    cur_user = server.ssh_user or "root"
    cur_pass = server.ssh_password
    cur_key  = server.ssh_key
    is_eu    = str(server.role).upper() in ("EU", "SERVERROLE.EU")
    use_sudo = (cur_user != "root")

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 1 — Проверка подключения
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step1", log_line="[1] Проверка подключения...")
    try:
        client = _connect(cur_ip, cur_port, cur_user,
                          password=cur_pass, private_key_pem=cur_key)
        code, out, _ = _exec(client,
            "echo OK && id && "
            "lsb_release -d 2>/dev/null || true && "
            "uptime -p 2>/dev/null || uptime && "
            "df -h / | tail -1 && "
            "free -h | grep Mem")
        client.close()
        if "OK" not in out:
            raise RuntimeError("Сервер не ответил на echo OK")
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        _update_setup(db, server, log_line="[1] ✅ Подключение установлено")
        for l in lines[1:]:  # пропускаем 'OK'
            _update_setup(db, server, log_line=f"[1]    {l}")
    except Exception as e:
        _update_setup(db, server, status="failed", error=str(e),
                      log_line=f"[1] ❌ Ошибка подключения: {e}")
        server.status = ServerStatus.NOT_CONFIGURED
        db.add(server); db.commit()
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 2 — Установка стека
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step2", log_line="[2] Установка стека...")

    client = _connect(cur_ip, cur_port, cur_user,
                      password=cur_pass, private_key_pem=cur_key)
    try:
        # 2.0 Очистка lock-файлов (один раз!) + apt-get update
        _update_setup(db, server, log_line="[2.0] Подготовка APT (очистка блокировок)...")
        _clear_apt_locks(client, db, server, use_sudo)
        code, _, err = _se(client,
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq", use_sudo,
            timeout=120)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.0] ⚠️ apt-get update: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.0] ✅ APT обновлён")

        # 2.1 Базовые зависимости
        _update_setup(db, server, log_line="[2.1] Установка базовых пакетов...")
        code, _, err = _se(client,
            "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
            "curl wget unzip git ca-certificates gnupg lsb-release", use_sudo,
            timeout=180)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.1] ⚠️ Базовые пакеты: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.1] ✅ Базовые пакеты установлены")

        # 2.2 Xray-core — устанавливаем через уже открытый client (без отдельного SSHClient)
        _update_setup(db, server, log_line="[2.2] Установка Xray-core...")
        XRAY_SCRIPT = r"""#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
echo "[*] Installing Xray-core..."
apt-get install -y -qq curl wget unzip 2>/dev/null

# Попытка 1: официальный скрипт
if bash <(curl -fsSL --retry 3 --retry-delay 2 \
    https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install 2>&1; then
    echo "[+] Xray installed via official script"
else
    echo "[!] Official script failed, trying direct binary download..."
    ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
    case "$ARCH" in
      amd64|x86_64) XRAY_ARCH="Xray-linux-64" ;;
      arm64|aarch64) XRAY_ARCH="Xray-linux-arm64-v8a" ;;
      *) XRAY_ARCH="Xray-linux-64" ;;
    esac
    XRAY_VER=$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4 | head -1)
    [ -z "$XRAY_VER" ] && XRAY_VER="v25.3.6"
    XRAY_URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VER}/${XRAY_ARCH}.zip"
    echo "[*] Downloading $XRAY_URL"
    curl -fsSL --retry 3 -o /tmp/xray.zip "$XRAY_URL"
    mkdir -p /usr/local/bin /usr/local/etc/xray /var/log/xray
    cd /tmp && unzip -o xray.zip xray -d /usr/local/bin/ 2>/dev/null || \
        (unzip -o xray.zip -d /tmp/xray_unpack/ && cp /tmp/xray_unpack/xray /usr/local/bin/xray)
    chmod +x /usr/local/bin/xray 2>/dev/null || true
    cat > /etc/systemd/system/xray.service << 'SVC_EOF'
[Unit]
Description=Xray Service
After=network.target
[Service]
User=nobody
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=on-failure
[Install]
WantedBy=multi-user.target
SVC_EOF
fi

mkdir -p /var/log/xray /usr/local/etc/xray
chmod 755 /var/log/xray
cat > /usr/local/etc/xray/config.json << 'XRAY_EOF'
{"log":{"loglevel":"warning"},"inbounds":[],"outbounds":[{"tag":"direct","protocol":"freedom","settings":{}}]}
XRAY_EOF
systemctl daemon-reload
systemctl enable xray
systemctl restart xray
echo "[+] Xray installed"
"""
        _xray_cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out, err = _exec(client, f"{_xray_cmd} << '__XRAY__'\n{XRAY_SCRIPT}\n__XRAY__", timeout=300)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.2] ❌ Xray: {(err or out)[:300]}")
        else:
            server.xray_installed = True
            db.add(server); db.commit()
            _update_setup(db, server, log_line="[2.2] ✅ Xray-core установлен")
            # Проверяем что xray запустился
            _, xray_status, _ = _exec(client, "systemctl is-active xray 2>/dev/null || echo inactive")
            first = next((l.strip() for l in xray_status.splitlines() if l.strip()), "")
            if first == "active":
                _update_setup(db, server, log_line="[2.2] ✅ Xray запущен")
            else:
                _update_setup(db, server, log_line=f"[2.2] ⚠️ Xray статус: {first or 'unknown'}")
            # Reality-ключи — напрямую через client
            _, keys_out, _ = _exec(client, "xray x25519 2>/dev/null || true", timeout=15)
            xray_pub = None
            for ln in keys_out.splitlines():
                if "Public key:" in ln:
                    xray_pub = ln.split(":", 1)[1].strip()
            if xray_pub:
                server.xray_public_key = xray_pub
                db.add(server); db.commit()
                _update_setup(db, server, log_line="[2.2] ✅ Reality-ключи сгенерированы")

        # 2.3 AmneziaWG
        _update_setup(db, server, log_line="[2.3] Установка AmneziaWG...")
        AWG_SCRIPT = """export DEBIAN_FRONTEND=noninteractive
echo "[*] Installing AmneziaWG..."
apt-get install -y -qq software-properties-common
add-apt-repository -y ppa:amnezia/ppa 2>/dev/null || true
apt-get update -qq
apt-get install -y -qq amneziawg amneziawg-tools
modprobe amneziawg 2>/dev/null || true
echo "[+] AmneziaWG installed"
"""
        _awg_cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out, err = _exec(client, f"{_awg_cmd} << '__AWG__'\n{AWG_SCRIPT}\n__AWG__", timeout=300)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.3] ❌ AmneziaWG: {err[:300]}")
        else:
            server.awg_installed = True
            # Генерируем серверные ключи AWG
            code2, keys_out, _ = _exec(client,
                "awg genkey | tee /tmp/awg_server.key | awg pubkey && "
                "cat /tmp/awg_server.key")
            if code2 == 0:
                lines = keys_out.strip().splitlines()
                if len(lines) >= 2:
                    server.awg_server_public_key = lines[0].strip()
            db.add(server); db.commit()
            _update_setup(db, server,
                log_line="[2.3] ✅ AmneziaWG установлен, запуск после генерации конфига")

        # 2.4 NaiveProxy — устанавливаем бинарник напрямую с GitHub (без Caddy)
        _update_setup(db, server, log_line="[2.4] Установка NaiveProxy (бинарник)...")
        NAIVE_SCRIPT = r"""export DEBIAN_FRONTEND=noninteractive
set -e
echo "[*] Installing NaiveProxy binary from GitHub releases..."

# Архитектура
ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
case "$ARCH" in
  amd64|x86_64) ARCH_TAG="linux-x64" ;;
  arm64|aarch64) ARCH_TAG="linux-arm64" ;;
  *) ARCH_TAG="linux-x64" ;;
esac

# Последняя версия
NAIVE_VERSION=$(curl -sf https://api.github.com/repos/klzgrad/naiveproxy/releases/latest   | grep '"tag_name"' | cut -d'"' -f4 | head -1)
if [ -z "$NAIVE_VERSION" ]; then
  echo "[!] Could not fetch version, trying fallback tag"
  NAIVE_VERSION=$(curl -sf https://github.com/klzgrad/naiveproxy/releases     | grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1)
fi
echo "[*] NaiveProxy version: ${NAIVE_VERSION}"

NAIVE_URL="https://github.com/klzgrad/naiveproxy/releases/download/${NAIVE_VERSION}/naiveproxy-${NAIVE_VERSION}-${ARCH_TAG}.tar.xz"
echo "[*] Downloading: $NAIVE_URL"

cd /tmp
rm -f naive.tar.xz
curl -fsSL -o naive.tar.xz "$NAIVE_URL"
tar -xf naive.tar.xz 2>/dev/null || unxz naive.tar.xz && tar -xf naive.tar 2>/dev/null || true

# Ищем бинарник
NAIVE_BIN=$(find /tmp -name "naive" -type f 2>/dev/null | head -1)
if [ -n "$NAIVE_BIN" ]; then
  cp "$NAIVE_BIN" /usr/local/bin/naive
  chmod +x /usr/local/bin/naive
  NAIVE_VER=$(/usr/local/bin/naive --version 2>/dev/null || echo "installed")
  echo "[+] NaiveProxy installed: $NAIVE_VER"
else
  echo "[!] naive binary not found in archive"
  ls /tmp/naiveproxy-* 2>/dev/null || true
  exit 1
fi

# Директория конфигов
mkdir -p /etc/naiveproxy
echo "[+] NaiveProxy setup complete"
"""
        _naive_cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out, err = _exec(client, f"{_naive_cmd} << '__NAIVE__'\n{NAIVE_SCRIPT}\n__NAIVE__", timeout=300)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.4] ❌ NaiveProxy: {err[:300]}")
        else:
            server.naiveproxy_installed = True
            # Версия
            _, ver_out, _ = _exec(client,
                "/usr/local/bin/naive --version 2>/dev/null || echo ''", timeout=10)
            ver = ver_out.strip().splitlines()[0] if ver_out.strip() else None
            if ver:
                server.caddy_version = ver  # reuse caddy_version field for naive version
            db.add(server); db.commit()
            _update_setup(db, server,
                log_line=f"[2.4] ✅ NaiveProxy установлен{(' (' + ver + ')') if ver else ''}")
            # Привязка поддомена делается позже в рамках настройки подключения
            pass

        # 2.5 WARP (только RU)
        if not is_eu:
            _update_setup(db, server, log_line="[2.5] Установка WARP...")
            from app.services.deploy_service import install_warp
            ok, msg = install_warp(server)
            if ok:
                server.warp_installed = True
                db.add(server); db.commit()
                _update_setup(db, server, log_line="[2.5] ✅ WARP установлен")
            else:
                _update_setup(db, server, log_line=f"[2.5] ❌ WARP: {msg}")

    except Exception as e:
        _update_setup(db, server, log_line=f"[2] ⚠️ Установка стека упала: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    _update_setup(db, server, log_line="[2] ✅ Установка стека завершена")

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 3 — Настройка безопасности
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step3", log_line="[3] Настройка безопасности...")

    client = _connect(cur_ip, cur_port, cur_user,
                      password=cur_pass, private_key_pem=cur_key)

    # Флаги безопасности — будут записаны в БД на шаге 4
    sec_password_auth_disabled = False
    sec_fail2ban_active        = False
    sec_ufw_active             = False
    sec_ssh_key_set            = False

    try:
        # 3.1 apt upgrade (только критичные пакеты — openssh-server, openssl)
        _update_setup(db, server, log_line="[3.1] Обновление критичных пакетов (SSH, OpenSSL)...")
        # Сначала убиваем unattended-upgrades чтобы не блокировал apt
        _se(client,
            "systemctl stop unattended-upgrades 2>/dev/null || true; "
            "pkill -9 -f unattended-upgrades 2>/dev/null || true; "
            "pkill -9 -f apt-get 2>/dev/null || true; "
            "pkill -9 -f dpkg 2>/dev/null || true; "
            "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true; "
            "dpkg --configure -a 2>/dev/null || true", use_sudo,
            timeout=30)
        code, _, err = _se(client,
            "DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y -qq "
            "-o DPkg::Lock::Timeout=60 "
            "openssh-server openssl 2>/dev/null || true", use_sudo,
            timeout=120)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.1] ⚠️ Обновление пакетов: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[3.1] ✅ Критичные пакеты обновлены")

        # 3.2 Fail2Ban + UFW — одной командой apt (с повторной попыткой при dpkg lock)
        _update_setup(db, server, log_line="[3.2] Установка Fail2Ban и UFW...")
        code, _, err = _se(client,
            "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban ufw", use_sudo,
            timeout=180)
        if code != 0:
            # Повторная попытка после очистки dpkg locks
            _update_setup(db, server, log_line=f"[3.2] ⚠️ Первая попытка: {err[:150]}. Очищаем lock и повторяем...")
            _se(client,
                "pkill -9 -f apt-get 2>/dev/null || true; "
                "pkill -9 -f dpkg 2>/dev/null || true; "
                "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null; "
                "dpkg --configure -a 2>/dev/null || true; sleep 5", use_sudo,
                timeout=30)
            code, _, err = _se(client,
                "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban ufw", use_sudo,
                timeout=180)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.2] ⚠️ Установка Fail2Ban/UFW не удалась: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[3.2] ✅ Fail2Ban и UFW установлены")

        # 3.3 Запуск и настройка Fail2Ban
        _update_setup(db, server, log_line="[3.3] Запуск и настройка Fail2Ban...")
        code, _, err = _se(client,
            "systemctl enable fail2ban && systemctl start fail2ban && "
            """cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
EOF""" + " && systemctl restart fail2ban", use_sudo,
            timeout=60)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.3] ⚠️ Fail2Ban: {err[:200]}")
        else:
            _, fb_status, _ = _se(client, "systemctl is-active fail2ban 2>/dev/null || echo inactive", use_sudo)
            fb_first = next((l.strip() for l in fb_status.splitlines() if l.strip()), "")
            if fb_first == "active":
                sec_fail2ban_active = True
                _update_setup(db, server, log_line="[3.3] ✅ Fail2Ban запущен")
            else:
                _update_setup(db, server, log_line=f"[3.3] ⚠️ Fail2Ban установлен, статус: {fb_first}")

        # 3.4 Настройка UFW
        # Используем текущий SSH порт (ещё не изменён на шаге 3.9)
        _update_setup(db, server, log_line="[3.4] Настройка UFW...")
        _current_ssh_port_for_ufw = cur_port  # порт ДО смены — откроем его в UFW
        _ufw = ("sudo -n ufw" if use_sudo else "ufw")
        ufw_cmds = (
            f"{_ufw} --force reset && "
            f"{_ufw} default deny incoming && "
            f"{_ufw} default allow outgoing && "
            f"{_ufw} allow {_current_ssh_port_for_ufw}/tcp && "
            f"{_ufw} allow 22/tcp && "
            f"{_ufw} allow 80/tcp && "
            f"{_ufw} allow 443/tcp && "
            f"{_ufw} allow 51820/udp && "
            f"{_ufw} allow 51821/udp"
        )
        if not is_eu:
            ufw_cmds += f" && {_ufw} allow 2408/udp"
        ufw_cmds += f" && DEBIAN_FRONTEND=noninteractive {_ufw} --force enable"
        code, _, err = _exec(client, ufw_cmds, timeout=60)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.4] ⚠️ UFW: {err[:200]}")
        else:
            _, ufw_status, _ = _exec(client, "sudo ufw status 2>/dev/null | head -1 || ufw status | head -1 || echo unknown")
            ufw_first = next((l.strip() for l in ufw_status.splitlines() if l.strip()), "")
            if "active" in ufw_first.lower():
                sec_ufw_active = True
                _update_setup(db, server, log_line="[3.4] ✅ UFW настроен и активен")
            else:
                _update_setup(db, server, log_line=f"[3.4] ⚠️ UFW: {ufw_first}")

        # 3.5 Новый пользователь
        _update_setup(db, server, log_line="[3.5] Создание нового SSH-пользователя...")
        new_user = _gen_username()
        _su = 'sudo -n ' if use_sudo else ''
        code, out, err = _exec(client,
            f"id {new_user} &>/dev/null || {_su}useradd -m -s /bin/bash {new_user} && "
            f"{_su}usermod -aG sudo {new_user} && "
            f"echo '{new_user} ALL=(ALL) NOPASSWD:ALL' | {_su}tee /etc/sudoers.d/{new_user} > /dev/null && "
            f"{_su}chmod 440 /etc/sudoers.d/{new_user} && "
            f"mkdir -p /home/{new_user}/.ssh && "
            f"chmod 700 /home/{new_user}/.ssh && "
            f"cp ~/.ssh/authorized_keys /home/{new_user}/.ssh/authorized_keys 2>/dev/null || true && "
            f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh && "
            f"echo created",
            timeout=60)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.5] ⚠️ Создание юзера: {err[:200]}")
            new_user = cur_user
        else:
            _update_setup(db, server, log_line=f"[3.5] ✅ Пользователь {new_user} создан")

        # 3.6 SSH-ключ Ed25519
        _update_setup(db, server, log_line="[3.6] Генерация SSH-ключа Ed25519...")
        new_priv, new_pub = _gen_ed25519_keypair()
        code, _, err = _exec(client,
            f"mkdir -p /home/{new_user}/.ssh && "
            f"echo '{new_pub}' >> /home/{new_user}/.ssh/authorized_keys && "
            f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh && "
            f"chmod 600 /home/{new_user}/.ssh/authorized_keys",
            timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.6] ⚠️ Добавление ключа: {err[:200]}")
        else:
            # Проверяем подключение по новому ключу
            try:
                test_cli = _connect(cur_ip, cur_port, new_user, private_key_pem=new_priv)
                _exec(test_cli, "echo KEY_OK")
                test_cli.close()
                cur_user = new_user
                cur_key  = new_priv
                cur_pass = None
                sec_ssh_key_set = True
                _update_setup(db, server, log_line="[3.6] ✅ SSH-ключ сгенерирован и проверен")
            except Exception as e:
                _update_setup(db, server, log_line=f"[3.6] ⚠️ Ключ создан, проверка не прошла: {e}")

        # 3.7 Смена пароля
        _update_setup(db, server, log_line="[3.7] Смена пароля пользователя...")
        new_password = _gen_password()
        code, _, err = _exec(client,
            (f"echo '{new_user}:{new_password}' | sudo -n chpasswd" if use_sudo else f"echo '{new_user}:{new_password}' | chpasswd"), timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.7] ⚠️ Смена пароля: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[3.7] ✅ Пароль обновлён")
            try:
                server.ssh_password_enc = encrypt_value(new_password)
            except AttributeError:
                pass

        # 3.8 Отключение парольной аутентификации SSH
        # ВАЖНО: на Ubuntu cloud-init создаёт drop-in /etc/ssh/sshd_config.d/50-cloud-init.conf
        # который перекрывает основной конфиг — нужно патчить оба файла
        _update_setup(db, server, log_line="[3.8] Отключение парольной аутентификации...")
        _sd = "sudo -n " if use_sudo else ""
        code, _, err = _exec(client,
            # Патчим основной конфиг
            f"{_sd}sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && "
            f"grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || {_sd}bash -c 'echo PasswordAuthentication no >> /etc/ssh/sshd_config' && "
            # Патчим все drop-in файлы (cloud-init, snap, etc.)
            f"for f in /etc/ssh/sshd_config.d/*.conf; do "
            f"  [ -f \"$f\" ] && {_sd}sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' \"$f\"; "
            "done; "
            # Перезагружаем sshd
            f"{_sd}systemctl reload sshd 2>/dev/null || {_sd}systemctl reload ssh 2>/dev/null || true",
            timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[3.8] ⚠️ Отключение password auth: {err[:200]}")
        else:
            sec_password_auth_disabled = True
            _update_setup(db, server, log_line="[3.8] ✅ Парольная аутентификация отключена (включая cloud-init drop-in)")

        # 3.9 Смена SSH-порта
        # Стратегия безопасной смены порта:
        # 1. Открываем новый порт в UFW (порт 22 НЕ закрываем до успешной проверки)
        # 2. Пишем новый порт в sshd_config
        # 3. Перезапускаем ssh через nohup (Ubuntu 24.04: ssh.socket + ssh.service)
        # 4. Проверяем новый порт — если OK, закрываем 22; если нет — откат
        _update_setup(db, server, log_line="[3.9] Смена SSH-порта...")
        new_port = _gen_ssh_port()

        # Шаг A: открываем новый порт в UFW (порт 22 пока оставляем открытым!)
        _exec(client, (f"sudo -n ufw allow {new_port}/tcp 2>/dev/null || true" if use_sudo else f"ufw allow {new_port}/tcp 2>/dev/null || true"), timeout=15)

        # Шаг B: меняем Port в sshd_config
        _exec(client,
            (f"sudo -n sed -i '/^#*Port /d' /etc/ssh/sshd_config && "
            f"sudo -n bash -c 'echo Port {new_port} >> /etc/ssh/sshd_config'"
            if use_sudo else
            f"sed -i '/^#*Port /d' /etc/ssh/sshd_config && "
            f"echo 'Port {new_port}' >> /etc/ssh/sshd_config"),
            timeout=15)

        # Шаг C: отключаем socket-activation (Ubuntu 24.04)
        # ssh.socket держит порт 22 жёстко; при его restart происходит
        # кратковременное закрытие порта → UFW блокирует → соединение рвётся.
        # Решение: выключаем сокет, переходим на классический sshd.service.
        _se(client,
            "systemctl disable ssh.socket 2>/dev/null || true && "
            "systemctl stop ssh.socket 2>/dev/null || true && "
            # Убираем старый override если есть
            "rm -f /etc/systemd/system/ssh.socket.d/port.conf && "
            "systemctl daemon-reload", use_sudo,
            timeout=15)

        # Шаг D: рестартуем ssh.service через nohup
        # Теперь sshd сам слушает порт из sshd_config (без сокета).
        # Порт 22 в UFW остаётся открытым до подтверждения нового порта.
        _exec(client,
            ("nohup bash -c "
            "'sleep 3 && "
            "sudo -n systemctl restart ssh.service 2>/dev/null || "
            "sudo -n systemctl restart sshd 2>/dev/null' "
            "> /tmp/sshd_restart.log 2>&1 &"
            if use_sudo else
            "nohup bash -c "
            "'sleep 3 && "
            "systemctl restart ssh.service 2>/dev/null || "
            "systemctl restart sshd 2>/dev/null' "
            "> /tmp/sshd_restart.log 2>&1 &"),
            timeout=8)

        # Шаг E: ждём и проверяем новый порт
        _update_setup(db, server, log_line=f"[3.9] ⏳ Ожидание SSH на порту {new_port}...")
        time.sleep(8)
        port_ok = False
        for attempt in range(4):
            _update_setup(db, server,
                log_line=f"[3.9] ⏳ Проверка порта {new_port}, попытка {attempt+1}/4...")
            try:
                test_cli = _connect(cur_ip, new_port, cur_user,
                                    private_key_pem=cur_key, timeout=10)
                # Порт новый работает — теперь закрываем старый 22 в UFW
                _exec(test_cli, ("sudo -n ufw delete allow 22/tcp 2>/dev/null || true" if use_sudo else "ufw delete allow 22/tcp 2>/dev/null || true"), timeout=10)
                test_cli.close()
                cur_port = new_port
                port_ok = True
                _update_setup(db, server, log_line=f"[3.9] ✅ SSH-порт изменён на {new_port}")
                break
            except Exception as e:
                if attempt < 3:
                    _update_setup(db, server,
                        log_line=f"[3.9] ⏳ Порт {new_port} ещё не готов ({e.__class__.__name__}), ждём...")
                    time.sleep(10)
                else:
                    # Новый порт не поднялся — откатываемся на 22
                    # Порт 22 в UFW ещё открыт, поэтому откат возможен
                    _update_setup(db, server, log_line="[3.9] ⚠️ Новый порт не ответил — откат на порт 22...")
                    try:
                        rb = _connect(cur_ip, 22, cur_user, private_key_pem=cur_key, timeout=10)
                        _exec(rb,
                            # Восстанавливаем конфиг
                            "sed -i '/^Port /d' /etc/ssh/sshd_config && "
                            "echo 'Port 22' >> /etc/ssh/sshd_config && "
                            # Восстанавливаем socket-activation для порта 22
                            "systemctl daemon-reload && "
                            "systemctl enable ssh.socket 2>/dev/null || true && "
                            # Рестарт через service (socket ещё не активен на этом порту)
                            "systemctl restart ssh.service 2>/dev/null || "
                            "systemctl restart sshd 2>/dev/null || true",
                            timeout=20)
                        rb.close()
                        cur_port = 22
                        _update_setup(db, server,
                            log_line="[3.9] ⚠️ Откат выполнен — SSH остаётся на порту 22")
                    except Exception as rb_e:
                        _update_setup(db, server,
                            log_line=f"[3.9] ⚠️ Откат не удался: {rb_e}")

        # Сохраняем финальные credentials в БД
        server.ssh_user        = cur_user
        server.ssh_user_actual = cur_user
        server.ssh_port        = cur_port
        server.ssh_port_actual = cur_port if port_ok else None
        server.ssh_password    = None
        if cur_key:
            server.ssh_key = cur_key
            try:
                server.ssh_private_key_enc = encrypt_value(cur_key)
            except AttributeError:
                pass
        db.add(server); db.commit()
        _update_setup(db, server,
                      log_line=f"[3] Credentials: user={cur_user} port={cur_port}")

        # Переподключаемся для шагов 4-5 — с fallback на оригинальные credentials
        try:
            client.close()
        except Exception:
            pass
        reconnected = False
        for rc_port in sorted(set([cur_port, 22])):
            for rc_key, rc_pass in [(cur_key, None), (cur_key, cur_pass), (None, cur_pass)]:
                try:
                    client = _connect(cur_ip, rc_port, cur_user,
                                      password=rc_pass, private_key_pem=rc_key,
                                      timeout=12)
                    cur_port = rc_port
                    reconnected = True
                    _update_setup(db, server,
                        log_line=f"[3] ✅ Переподключение: {cur_user}@{cur_ip}:{rc_port}")
                    break
                except Exception:
                    pass
            if reconnected:
                break
        if not reconnected:
            _update_setup(db, server, status="failed",
                          error="Не удалось переподключиться после шага 3",
                          log_line="[3] ❌ Переподключение не удалось — настройка прервана")
            server.status = ServerStatus.NOT_CONFIGURED
            db.add(server); db.commit()
            return

    except Exception as e:
        _update_setup(db, server, log_line=f"[3] ⚠️ Шаг безопасности упал: {e}")
        try:
            client.close()
        except Exception:
            pass
        # Пробуем восстановить соединение
        connected = False
        for fb_port in sorted(set([cur_port, 22])):
            for fb_key, fb_pass in [(cur_key, None), (None, cur_pass)]:
                try:
                    client = _connect(cur_ip, fb_port, cur_user,
                                      password=fb_pass, private_key_pem=fb_key)
                    cur_port = fb_port
                    connected = True
                    break
                except Exception:
                    pass
            if connected:
                break
        if not connected:
            _update_setup(db, server, status="failed",
                          error="Потеряно SSH-соединение после шага 3",
                          log_line="[3] ❌ Не удалось восстановить SSH-соединение")
            server.status = ServerStatus.NOT_CONFIGURED
            db.add(server); db.commit()
            return

    _update_setup(db, server, log_line="[3] ✅ Настройка безопасности завершена")

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 4 — Сбор информации о сервере + security flags в БД
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step4", log_line="[4] Сбор информации о сервере...")
    try:
        # Определяем страну по IP через ip-api.com (если ещё не определена)
        if not server.country or server.country in ("??", ""):
            _update_setup(db, server, log_line="[4] ⏳ Определение страны по IP...")
            try:
                import urllib.request, json as _json
                geo_url = f"http://ip-api.com/json/{server.ip}?fields=status,country,countryCode"
                with urllib.request.urlopen(geo_url, timeout=8) as _r:
                    _geo = _json.loads(_r.read().decode())
                if _geo.get("status") == "success" and _geo.get("countryCode"):
                    server.country = _geo["countryCode"].upper()
                    db.add(server); db.commit()
                    _update_setup(db, server,
                        log_line=f"[4] ✅ Страна определена: {_geo['country']} ({server.country})")
                else:
                    _update_setup(db, server, log_line="[4] ⚠️ Страна не определена (ip-api)")
            except Exception as _ge:
                _update_setup(db, server, log_line=f"[4] ⚠️ Гео-запрос не удался: {_ge}")

        _, tz_out,   _ = _exec(client,
            "cat /etc/timezone 2>/dev/null || "
            "timedatectl | grep 'Time zone' | awk '{print $3}'")
        _, xray_v,   _ = _exec(client, "xray version 2>/dev/null | head -1 || echo ''")
        _, caddy_v,  _ = _exec(client,
            "/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || "
            "caddy version 2>/dev/null | head -1 || echo ''")
        _, awg_v,    _ = _exec(client, "awg --version 2>/dev/null | head -1 || echo ''")

        server.server_timezone = tz_out.strip() or None
        server.xray_version    = (xray_v.strip()[:50]  or None)
        server.caddy_version   = (caddy_v.strip()[:50] or None)
        server.awg_version     = (awg_v.strip()[:50]   or None)

        if not is_eu:
            _, warp_v, _ = _exec(client,
                "warp-cli --version 2>/dev/null | head -1 || echo ''")
            server.warp_version = warp_v.strip()[:50] or None

        # ── Security flags — записываем в БД ──────────────────────────────
        # Перепроверяем реальный статус на сервере (надёжнее флагов из шага 3)
        _, fb_chk, _  = _exec(client, "systemctl is-active fail2ban 2>/dev/null || echo inactive")
        _, ufw_chk, _ = _exec(client, "sudo ufw status 2>/dev/null | head -1 || ufw status 2>/dev/null | head -1 || echo unknown")
        # ВАЖНО: PasswordAuthentication проверяем с учётом drop-in файлов (cloud-init и др.)
        # Если хоть один файл содержит "PasswordAuthentication yes" — auth включена
        _, pw_chk, _  = _exec(client,
            "grep -rE '^PasswordAuthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null || echo ''")

        fb_first  = next((l.strip() for l in fb_chk.splitlines()  if l.strip()), "")
        ufw_first = next((l.strip() for l in ufw_chk.splitlines() if l.strip()), "")
        # Считаем auth отключённой только если нигде нет "yes"
        pw_lines = [l.strip().lower() for l in pw_chk.splitlines() if "passwordauthentication" in l.lower()]
        sec_fail2ban_active        = (fb_first  == "active")
        sec_ufw_active             = ("active" in ufw_first.lower())
        # password auth отключена если все строки содержат "no" (или строк нет вообще — default=yes, считаем включённой)
        sec_password_auth_disabled = bool(pw_lines) and all("no" in l for l in pw_lines)
        sec_ssh_key_set            = bool(cur_key)

        # ── Сохраняем ВСЕ параметры безопасности и SSH-доступа ──────────────────
        # sec_* флаги
        server.sec_fail2ban       = sec_fail2ban_active
        server.sec_ufw            = sec_ufw_active
        server.sec_password_login = not sec_password_auth_disabled   # True = пароль включён (плохо)
        server.sec_ssh_key        = sec_ssh_key_set

        # Актуальные SSH-параметры после харденинга
        server.ssh_user_actual = cur_user
        server.ssh_port_actual = cur_port

        # Зашифрованные credentials
        if cur_key:
            try:
                server.ssh_private_key_enc = encrypt_value(cur_key)
            except Exception as _e:
                _update_setup(db, server, log_line=f"[4] ⚠️ Не удалось зашифровать SSH-ключ: {_e}")
                server.ssh_key = cur_key   # fallback — сохраняем plain
        if cur_pass:
            try:
                server.ssh_password_enc = encrypt_value(cur_pass)
                server.ssh_password = None  # убираем plain-text пароль
            except Exception as _e:
                _update_setup(db, server, log_line=f"[4] ⚠️ Не удалось зашифровать пароль: {_e}")

        # Обновляем основные поля SSH (используются при последующих подключениях)
        server.ssh_user = cur_user
        server.ssh_port = cur_port
        if cur_key:
            server.ssh_key = cur_key

        db.add(server); db.commit()

        # Проверяем что хотя бы один параметр прочитан (признак живого SSH-соединения)
        if not server.server_timezone and not server.xray_version and not server.awg_version:
            _update_setup(db, server, status="failed",
                          error="SSH-соединение по новым credentials не работает",
                          log_line="[4] ❌ Данные не прочитаны — проверьте SSH-доступ")
            server.status = ServerStatus.NOT_CONFIGURED
            db.add(server); db.commit()
            try: client.close()
            except Exception: pass
            return

        # Логируем всё собранное
        _update_setup(db, server, log_line="[4] ✅ Информация собрана")
        _update_setup(db, server, log_line=f"[4]    Timezone  : {server.server_timezone or '—'}")
        _update_setup(db, server, log_line=f"[4]    Xray      : {server.xray_version    or '—'}")
        _update_setup(db, server, log_line=f"[4]    AWG       : {server.awg_version     or '—'}")
        _update_setup(db, server, log_line=f"[4]    Caddy     : {server.caddy_version   or '—'}")
        if not is_eu:
            _update_setup(db, server, log_line=f"[4]    WARP      : {server.warp_version or '—'}")
        _update_setup(db, server, log_line=
            f"[4]    SSH       : {server.ssh_user}@{server.ip}:{server.ssh_port}")
        _update_setup(db, server, log_line=
            f"[4]    Key       : {'✅ сохранён' if sec_ssh_key_set else '❌ нет'}")
        _update_setup(db, server, log_line=
            f"[4]    Fail2Ban  : {'✅ активен' if sec_fail2ban_active else '⚠️ неактивен'}")
        _update_setup(db, server, log_line=
            f"[4]    UFW       : {'✅ активен' if sec_ufw_active else '⚠️ неактивен'}")
        _update_setup(db, server, log_line=
            f"[4]    Passwd auth: {'✅ отключена' if sec_password_auth_disabled else '⚠️ включена'}")

    except Exception as e:
        _update_setup(db, server, status="failed",
                      error=f"Ошибка сбора данных сервера: {e}",
                      log_line=f"[4] ❌ Сбор информации не удался: {e}")
        server.status = ServerStatus.NOT_CONFIGURED
        db.add(server); db.commit()
        try: client.close()
        except Exception: pass
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 5 — Финальная проверка (install vs start — раздельно)
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step5", log_line="[5] Финальная проверка...")

    # Критичные сервисы (без них setup = failed)
    # Для AWG и Caddy проверяем только факт установки (пакет), не запуск
    critical_ok = True

    checks = [
        # (label, install_cmd, run_cmd_or_None, is_critical)
        # run_cmd=None означает "запускается после конфига, проверяем только установку"
        ("SSH",
            "which sshd || dpkg -l openssh-server 2>/dev/null | grep -q '^ii'",
            "echo ALIVE",
            True),
        ("Xray",
            "which xray || test -f /usr/local/bin/xray",
            "systemctl is-active xray 2>/dev/null || echo inactive",
            True),
        ("AmneziaWG",
            "which awg || dpkg -l amneziawg 2>/dev/null | grep -q '^ii'",
            None,  # запуск после генерации конфига — не проверяем
            False),
        ("Caddy (NaiveProxy)",
            "which caddy || test -f /usr/local/bin/caddy-naive || test -f /usr/local/bin/naive",
            None,  # запуск после генерации конфига — не проверяем
            False),
        ("Fail2Ban",
            "which fail2ban-server || dpkg -l fail2ban 2>/dev/null | grep -q '^ii'",
            "systemctl is-active fail2ban 2>/dev/null || echo inactive",
            False),
        ("UFW",
            "which ufw || dpkg -l ufw 2>/dev/null | grep -q '^ii'",
            "sudo ufw status 2>/dev/null | head -1 || ufw status 2>/dev/null | head -1 || echo unknown",
            False),
    ]
    if not is_eu:
        checks.append((
            "WARP",
            "which warp-cli || dpkg -l cloudflare-warp 2>/dev/null | grep -q '^ii'",
            "warp-cli status 2>/dev/null | head -1 || echo unknown",
            False,
        ))

    for name, install_cmd, run_cmd, is_critical in checks:
        try:
            # Проверка установки
            code_i, _, _ = _exec(client, install_cmd, timeout=10)
            installed = (code_i == 0)

            if not installed:
                icon = "❌" if is_critical else "⚠️"
                _update_setup(db, server, log_line=f"[5] {icon} {name}: не установлен")
                if is_critical:
                    critical_ok = False
                continue

            # Если run_cmd=None — сервис запускается по конфигу
            if run_cmd is None:
                _update_setup(db, server,
                    log_line=f"[5] ✅ {name}: установлен, запуск после генерации конфига")
                continue

            # Проверка запуска
            code_r, out_r, _ = _exec(client, run_cmd, timeout=15)
            first_line = next(
                (l.strip() for l in out_r.splitlines() if l.strip()), ""
            ).lower()

            is_up   = first_line in ("active", "alive") or "connected" in first_line or "status: active" in first_line
            is_down = first_line in ("inactive", "failed", "activating", "deactivating") or "status: inactive" in first_line
            display = out_r.splitlines()[0].strip() if out_r.strip() else "(нет вывода)"

            if name == "SSH":
                # SSH: критичная проверка через echo ALIVE
                if "alive" in first_line or code_r == 0:
                    _update_setup(db, server, log_line=f"[5] ✅ SSH: установлен и доступен")
                else:
                    _update_setup(db, server, log_line=f"[5] ❌ SSH: недоступен ({display})")
                    critical_ok = False
            elif is_up:
                _update_setup(db, server, log_line=f"[5] ✅ {name}: установлен и запущен")
            elif is_down:
                icon = "❌" if is_critical else "⚠️"
                _update_setup(db, server, log_line=f"[5] {icon} {name}: установлен, не запущен ({display})")
                if is_critical:
                    critical_ok = False
            else:
                _update_setup(db, server, log_line=f"[5] ℹ️ {name}: {display}")

        except Exception as e:
            _update_setup(db, server, log_line=f"[5] ⚠️ {name}: ошибка проверки ({e})")

    try:
        client.close()
    except Exception:
        pass

    # Финальный статус
    if critical_ok:
        server.setup_status = "done"
        server.status       = ServerStatus.ONLINE
        _update_setup(db, server,
            log_line="[setup] ✅ Настройка завершена успешно. Критичные сервисы работают.")
    else:
        server.setup_status = "failed"
        server.status       = ServerStatus.NOT_CONFIGURED
        _update_setup(db, server,
            log_line="[setup] ❌ Настройка завершена с ошибками. Проверьте критичные сервисы.")

    db.add(server); db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Автопривязка поддомена NaiveProxy
# ─────────────────────────────────────────────────────────────────────────────

def _try_link_naiveproxy_subdomain(db: Session, server: Server,
                                   client: paramiko.SSHClient, is_eu: bool):
    try:
        from app.models.domain import Subdomain
        stype = "naiveproxy_eu" if is_eu else "naiveproxy_ru"
        sub = (db.query(Subdomain)
               .filter(Subdomain.subdomain_type == stype,
                       Subdomain.status == "active",
                       Subdomain.server_id == None)
               .first())
        if not sub:
            return  # нет свободного поддомена — тихо пропускаем
        server.naiveproxy_subdomain_id = sub.id
        sub.server_id = server.id
        db.add(sub); db.add(server); db.commit()
        _update_setup(db, server, log_line=f"[2.4] 🔗 Привязан поддомен {sub.full_domain}")
    except Exception as e:
        pass  # Автопривязка поддомена не выполняется на этапе настройки


# ─────────────────────────────────────────────────────────────────────────────
# Статус для API (polling)
# ─────────────────────────────────────────────────────────────────────────────

def get_setup_status(server: Server) -> dict:
    log_lines = (server.setup_log or "").strip().split("\n") if server.setup_log else []
    return {
        "setup_status": server.setup_status or "not_started",
        "setup_step":   server.setup_step,
        "setup_error":  server.setup_error,
        "log":          log_lines,
    }
