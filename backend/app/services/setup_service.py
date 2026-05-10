"""
Setup Service — автоматическая настройка сервера при создании.

Шаги:
  1. Проверка подключения
  2. Установка стека (xray, awg, naiveproxy+caddy, warp для RU)
     ★ ОПТИМИЗАЦИЯ: единый apt-install всех пакетов + параллельная установка компонентов
  3. Настройка безопасности (batch-скрипты вместо отдельных SSH-вызовов)
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
import threading
from typing import Optional, Tuple

import paramiko
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.server import Server, ServerRole, ServerStatus
from app.models.domain import Domain

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
    """Случайный порт в диапазоне 10000–65000."""
    return random.randint(10000, 65000)


def _gen_username() -> str:
    suffix = random.randint(1000, 9999)
    return f"vpnadmin{suffix}"


def _gen_ed25519_keypair() -> Tuple[str, str]:
    """Генерирует пару Ed25519, возвращает (private_pem, public_openssh)."""
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

    return -1, "".join(out_chunks), "".join(err_chunks)


def _s(cmd: str, use_sudo: bool) -> str:
    if not use_sudo:
        return cmd
    cmd = cmd.strip()
    if cmd.startswith("sudo ") or cmd.startswith("nohup ") or cmd.startswith("echo "):
        return cmd
    return "sudo -n " + cmd


def _se(client: paramiko.SSHClient, cmd: str, use_sudo: bool, timeout: int = 120) -> tuple:
    return _exec(client, _s(cmd, use_sudo), timeout=timeout)


def _clear_apt_locks(client: paramiko.SSHClient, use_sudo: bool = False) -> None:
    """Одноразовая очистка dpkg/apt lock."""
    _se(client,
        "systemctl stop unattended-upgrades 2>/dev/null || true; "
        "pkill -9 -f unattended-upgrades 2>/dev/null || true; "
        "pkill -9 -f apt-get 2>/dev/null || true; "
        "sleep 1", use_sudo,
        timeout=15)

    wait_cmd = (
        "for i in $(seq 1 30); do "
        "pgrep -x apt-get >/dev/null 2>&1 || "
        "pgrep -x dpkg    >/dev/null 2>&1 || "
        "pgrep -f unattended-upgrades >/dev/null 2>&1 || "
        "{ echo FREE; break; }; "
        "sleep 3; done"
    )
    _, out, _ = _exec(client, wait_cmd, timeout=100)

    if "FREE" not in out:
        _se(client,
            "rm -f /var/lib/dpkg/lock-frontend "
            "/var/lib/dpkg/lock "
            "/var/cache/apt/archives/lock 2>/dev/null; "
            "dpkg --configure -a 2>/dev/null || true", use_sudo,
            timeout=60)


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



# ─────────────────────────────────────────────────────────────────────────────
# Auto-DNS: автоматическое назначение домена EU-серверу через Porkbun
# ─────────────────────────────────────────────────────────────────────────────

def _auto_assign_domain(db: Session, server: Server) -> None:
    """
    Автоматически создаёт DNS A-запись для EU-сервера и сохраняет server.domain.

    Алгоритм:
    1. Ищем активный Domain с Porkbun API ключами в БД
    2. Генерируем имя поддомена из названия сервера (например "fin1" из "FIN 1")
    3. Создаём A-запись через Porkbun API (синхронно через requests)
    4. Сохраняем full domain в server.domain и обновляем БД

    Вызывается из setup_service._run() на шаге 4.5 для EU-серверов.
    Fallback: если Porkbun API недоступен или ключей нет — пропускаем без ошибки.
    """
    import re
    import requests as _req

    # 1. Найти активный домен с Porkbun ключами
    domain_obj = db.query(Domain).filter(
        Domain.porkbun_api_key != None,
        Domain.porkbun_secret_key != None,
    ).first()

    if not domain_obj:
        logger.warning("auto_assign_domain: no Domain with Porkbun keys found in DB")
        return

    api_key    = domain_obj.porkbun_api_key
    secret_key = domain_obj.porkbun_secret_key
    base_domain = domain_obj.name  # e.g. "milkyims.com"

    # 2. Генерируем поддомен из имени сервера
    # "FIN 1" → "fin1", "SWE 2" → "swe2", "Helsinki EU" → "helsinkieu"
    raw = (server.name or f"eu{server.id}").lower()
    subdomain = re.sub(r"[^a-z0-9]", "", raw) or f"eu{server.id}"

    # Проверяем — не занят ли уже этот поддомен другим сервером
    existing = db.query(Server).filter(
        Server.domain.like(f"{subdomain}.{base_domain}%"),
        Server.id != server.id,
    ).first()
    if existing:
        # Добавляем числовой суффикс чтобы не конфликтовать
        subdomain = f"{subdomain}{server.id}"

    full_domain = f"{subdomain}.{base_domain}"
    target_ip   = server.ip

    logger.info(f"auto_assign_domain: creating A-record {full_domain} → {target_ip}")

    # 3. Создаём A-запись через Porkbun REST API (синхронно)
    PORKBUN_BASE = "https://api.porkbun.com/api/json/v3"
    try:
        resp = _req.post(
            f"{PORKBUN_BASE}/dns/create/{base_domain}",
            json={
                "apikey":       api_key,
                "secretapikey": secret_key,
                "name":         subdomain,
                "type":         "A",
                "content":      target_ip,
                "ttl":          "600",
            },
            timeout=20,
        )
        data = resp.json()
        if data.get("status") != "SUCCESS":
            logger.warning(
                f"auto_assign_domain: Porkbun returned error: {data.get('message')}"
            )
            # Check if record already exists (idempotency)
            if "already exists" in str(data.get("message", "")).lower():
                logger.info(f"auto_assign_domain: A-record already exists for {full_domain}")
            else:
                return
        else:
            record_id = data.get("id")
            logger.info(f"auto_assign_domain: A-record created, id={record_id}")
    except Exception as e:
        logger.warning(f"auto_assign_domain: Porkbun API call failed: {e}")
        return

    # 4. Сохраняем домен в БД
    server.domain = full_domain
    db.add(server)
    db.commit()
    logger.info(f"auto_assign_domain: server {server.id} domain set to {full_domain}")


def _run(db: Session, server: Server):
    _update_setup(db, server, status="in_progress", step="step1",
                  log_line="[setup] Начинаем настройку сервера")
    server.status = ServerStatus.SETTING_UP
    db.add(server); db.commit()

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
        for l in lines[1:]:
            _update_setup(db, server, log_line=f"[1]    {l}")
    except Exception as e:
        _update_setup(db, server, status="failed", error=str(e),
                      log_line=f"[1] ❌ Ошибка подключения: {e}")
        server.status = ServerStatus.NOT_CONFIGURED
        db.add(server); db.commit()
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 2 — Установка стека
    # ★ ОПТИМИЗАЦИЯ 1: единый apt-get install для всех пакетов
    # ★ ОПТИМИЗАЦИЯ 2: параллельная установка Xray + AWG + Caddy
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step2", log_line="[2] Установка стека...")

    client = _connect(cur_ip, cur_port, cur_user,
                      password=cur_pass, private_key_pem=cur_key)
    try:
        # ── 2.0 Очистка locks + ЕДИНЫЙ APT-INSTALL ──────────────────────────
        # Вместо 4 отдельных apt-get вызовов (update + базовые + security + f2b/ufw)
        # делаем один — экономим ~60-90 сек на apt overhead и повторных lock-ожиданиях
        _update_setup(db, server, log_line="[2.0] Подготовка APT и установка всех пакетов...")
        _clear_apt_locks(client, use_sudo)

        APT_PREP_SCRIPT = """export DEBIAN_FRONTEND=noninteractive
set -e
# Единый apt-get update
apt-get update -qq

# Единый install: базовые + security + fail2ban + ufw + awg-deps
# Устанавливаем всё за один вызов — один lock, один pass по индексу
apt-get install -y -qq --no-install-recommends \
    curl wget unzip git ca-certificates gnupg lsb-release \
    software-properties-common \
    openssh-server openssl \
    fail2ban ufw

echo "[+] All base packages installed"
"""
        _apt_cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out, err = _exec(client,
            f"{_apt_cmd} << '__APT__'\n{APT_PREP_SCRIPT}\n__APT__",
            timeout=240)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.0] ⚠️ APT: {err[:300]}")
        else:
            _update_setup(db, server, log_line="[2.0] ✅ Все базовые пакеты установлены")

        # ── 2.1-2.4 Параллельная установка компонентов VPN-стека ────────────
        # Xray + AWG + Caddy не зависят друг от друга — запускаем через threads
        # Каждый поток открывает свой SSH-клиент (paramiko не thread-safe для одного клиента)
        _update_setup(db, server, log_line="[2.1] Параллельная установка Xray + AmneziaWG + Caddy...")

        results = {}   # thread-safe: каждый поток пишет в свой ключ
        lock = threading.Lock()

        def _log(msg: str):
            """Потокобезопасная запись в лог."""
            with lock:
                _update_setup(db, server, log_line=msg)

        # ── Поток 1: Xray-core ───────────────────────────────────────────────
        def install_xray():
            try:
                cli = _connect(cur_ip, cur_port, cur_user,
                               password=cur_pass, private_key_pem=cur_key)
                XRAY_SCRIPT = r"""#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
echo "[*] Installing Xray-core..."

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
    XRAY_VER=$(curl -fsSL --max-time 8 https://api.github.com/repos/XTLS/Xray-core/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4 | head -1)
    [ -z "$XRAY_VER" ] && XRAY_VER="v25.3.6"
    XRAY_URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VER}/${XRAY_ARCH}.zip"
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
echo "[+] Xray done"
"""
                _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
                code, out, err = _exec(cli,
                    f"{_cmd} << '__XRAY__'\n{XRAY_SCRIPT}\n__XRAY__",
                    timeout=300)
                if code != 0:
                    _log(f"[2.2] ❌ Xray: {(err or out)[:300]}")
                    results['xray'] = False
                else:
                    # Reality-ключи
                    _, keys_out, _ = _exec(cli, "xray x25519 2>/dev/null || true", timeout=15)
                    xray_pub = None
                    for ln in keys_out.splitlines():
                        if "Public key:" in ln:
                            xray_pub = ln.split(":", 1)[1].strip()
                    with lock:
                        server.xray_installed = True
                        if xray_pub:
                            server.xray_public_key = xray_pub
                        db.add(server); db.commit()
                    # Статус сервиса
                    _, st, _ = _exec(cli,
                        "systemctl is-active xray 2>/dev/null || echo inactive")
                    first = next((l.strip() for l in st.splitlines() if l.strip()), "")
                    _log(f"[2.2] ✅ Xray-core установлен, сервис: {first}")
                    if xray_pub:
                        _log("[2.2] ✅ Reality-ключи сгенерированы")
                    results['xray'] = True
                cli.close()
            except Exception as e:
                _log(f"[2.2] ❌ Xray: исключение: {e}")
                results['xray'] = False

        # ── Поток 2: AmneziaWG ───────────────────────────────────────────────
        def install_awg():
            try:
                cli = _connect(cur_ip, cur_port, cur_user,
                               password=cur_pass, private_key_pem=cur_key)
                AWG_SCRIPT = """export DEBIAN_FRONTEND=noninteractive
set -e

# ── Метод 1: PPA (может упасть с 503 если Launchpad недоступен) ──────────
AWG_VIA_PPA=0
if add-apt-repository -y ppa:amnezia/ppa 2>&1; then
    if apt-get update -qq 2>&1 && apt-get install -y -qq amneziawg amneziawg-tools 2>&1; then
        AWG_VIA_PPA=1
        echo "[+] AWG installed via PPA"
    else
        echo "[!] PPA apt-get install failed, will try fallback" >&2
    fi
else
    echo "[!] add-apt-repository failed (503?), will try fallback" >&2
fi

# ── Метод 2: fallback — реальный awg binary из amneziawg-tools releases ──
if [ "$AWG_VIA_PPA" = "0" ]; then
    echo "[*] Fallback: installing awg binary from amneziawg-tools GitHub releases..."
    mkdir -p /tmp/awg_tools

    # Узнаём последний тег amneziawg-tools
    TOOLS_VER=$(curl -fsSL --max-time 10 \
        https://api.github.com/repos/amnezia-vpn/amneziawg-tools/releases/latest \
        2>/dev/null | grep '"tag_name"' | cut -d'"' -f4 | head -1)
    [ -z "$TOOLS_VER" ] && TOOLS_VER="v1.0.20260223"
    echo "[*] amneziawg-tools release: $TOOLS_VER"

    # Скачиваем ubuntu zip — содержит готовые бинарники awg и awg-quick
    TOOLS_ZIP_URL="https://github.com/amnezia-vpn/amneziawg-tools/releases/download/${TOOLS_VER}/ubuntu-22.04-amneziawg-tools.zip"
    if curl -fsSL --retry 3 --retry-delay 2 --max-time 60 \
            -o /tmp/awg_tools/awg-tools.zip "$TOOLS_ZIP_URL" 2>&1; then
        cd /tmp/awg_tools
        unzip -o awg-tools.zip 2>/dev/null || true
        # Ищем бинарник awg в распакованном архиве
        AWG_BIN=$(find /tmp/awg_tools -name 'awg' -type f ! -name '*.sha256' 2>/dev/null | head -1)
        if [ -n "$AWG_BIN" ]; then
            cp "$AWG_BIN" /usr/local/bin/awg
            chmod +x /usr/local/bin/awg
            AWG_QUICK_BIN=$(find /tmp/awg_tools -name 'awg-quick' -type f 2>/dev/null | head -1)
            [ -n "$AWG_QUICK_BIN" ] && cp "$AWG_QUICK_BIN" /usr/local/bin/awg-quick && chmod +x /usr/local/bin/awg-quick
            echo "[+] awg binary installed from tools zip: $(awg --version 2>/dev/null || echo ok)"
        else
            echo "[!] awg binary not found in zip" >&2
        fi
    else
        echo "[!] amneziawg-tools zip download failed" >&2
    fi

    # Пробуем установить ядерный модуль через dkms (нужен для modprobe amneziawg)
    apt-get install -y -qq dkms linux-headers-$(uname -r) linux-headers-generic 2>/dev/null || true
    # Пробуем dkms-пакет из amnezia репо
    KMOD_VER=$(curl -fsSL --max-time 10 \
        https://api.github.com/repos/amnezia-vpn/amneziawg-linux-kernel-module/releases/latest \
        2>/dev/null | grep '"tag_name"' | cut -d'"' -f4 | head -1)
    [ -z "$KMOD_VER" ] && KMOD_VER="v1.0.20250521"
    KMOD_DEB_URL="https://github.com/amnezia-vpn/amneziawg-linux-kernel-module/releases/download/${KMOD_VER}/amneziawg-dkms_${KMOD_VER#v}-1_all.deb"
    if curl -fsSL --retry 2 --max-time 60 -o /tmp/awg_tools/awg-dkms.deb "$KMOD_DEB_URL" 2>&1; then
        dpkg -i /tmp/awg_tools/awg-dkms.deb 2>&1 || apt-get install -f -y -qq 2>&1 || true
    fi
fi

modprobe amneziawg 2>/dev/null || modprobe wireguard 2>/dev/null || true
# Проверяем именно awg — wireguard-tools НЕ является заменой
which awg || (echo 'AWG binary not found after all install attempts' >&2 && exit 1)
echo "[+] AWG done"
"""
                _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
                code, out, err = _exec(cli,
                    f"{_cmd} << '__AWG__'\n{AWG_SCRIPT}\n__AWG__",
                    timeout=300)
                if code != 0:
                    awg_err = (err or out or "нет вывода").strip()[:400]
                    _log(f"[2.3] ❌ AmneziaWG не установлен: {awg_err}")
                    results['awg'] = False
                else:
                    # Генерируем серверные ключи
                    code2, keys_out, _ = _exec(cli,
                        "awg genkey | tee /tmp/awg_server.key | awg pubkey && "
                        "cat /tmp/awg_server.key",
                        timeout=15)
                    with lock:
                        server.awg_installed = True
                        if code2 == 0:
                            lines = keys_out.strip().splitlines()
                            if len(lines) >= 2:
                                server.awg_server_public_key  = lines[0].strip()
                                server.awg_server_private_key = lines[1].strip()
                            elif len(lines) == 1:
                                server.awg_server_public_key = lines[0].strip()
                                _log("[2.3] ⚠️ AWG: приватный ключ не получен")
                        else:
                            _log("[2.3] ⚠️ AWG: ошибка генерации ключей")
                        db.add(server); db.commit()
                    _log("[2.3] ✅ AmneziaWG установлен, запуск после генерации конфига")
                    results['awg'] = True
                cli.close()
            except Exception as e:
                _log(f"[2.3] ❌ AWG: исключение: {e}")
                results['awg'] = False

        # ── Поток 3: Caddy + forwardproxy ────────────────────────────────────
        def install_caddy():
            try:
                cli = _connect(cur_ip, cur_port, cur_user,
                               password=cur_pass, private_key_pem=cur_key)
                CADDY_SCRIPT = r"""export DEBIAN_FRONTEND=noninteractive
set -e
echo "[*] Installing Caddy with forwardproxy plugin..."

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
case "$ARCH" in
  amd64|x86_64) IS_AMD64=1 ;;
  *) IS_AMD64=0 ;;
esac

cd /tmp
rm -f caddy-naive.tar.xz

if [ "$IS_AMD64" = "1" ]; then
  FP_VER=$(curl -sf --max-time 8 "https://api.github.com/repos/klzgrad/forwardproxy/releases/latest" \
    | grep '"tag_name"' | cut -d'"' -f4 | head -1)
  [ -z "$FP_VER" ] && FP_VER="v2.10.0-naive"
  CADDY_URL="https://github.com/klzgrad/forwardproxy/releases/download/${FP_VER}/caddy-forwardproxy-naive.tar.xz"
  if ! curl -fsSL --retry 3 --retry-delay 2 -o caddy-naive.tar.xz "$CADDY_URL"; then
    echo "[!] Download failed: $CADDY_URL" >&2; exit 1
  fi
  tar -xJf caddy-naive.tar.xz 2>/dev/null || tar -xf caddy-naive.tar.xz 2>/dev/null || true
  CADDY_BIN=$(find /tmp/caddy-forwardproxy-naive -name "caddy" -type f 2>/dev/null | head -1)
  [ -z "$CADDY_BIN" ] && CADDY_BIN=$(find /tmp -maxdepth 3 -name "caddy" -type f ! -name "*.tar*" 2>/dev/null | head -1)
  [ -z "$CADDY_BIN" ] && { echo "[!] Caddy binary not found in archive" >&2; exit 1; }
else
  # arm64: xcaddy build
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-xcaddy-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/debian.deb.txt' > /etc/apt/sources.list.d/caddy-xcaddy.list
  apt-get update -qq && apt-get install -y -qq xcaddy golang-go
  xcaddy build --with github.com/klzgrad/forwardproxy@latest --output /tmp/caddy
  CADDY_BIN="/tmp/caddy"
fi

cp "$CADDY_BIN" /usr/local/bin/caddy-naive
chmod +x /usr/local/bin/caddy-naive
mkdir -p /etc/caddy /var/log/caddy /var/lib/caddy
CADDY_VER=$(/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || echo "installed")
echo "[+] Caddy done: $CADDY_VER"
"""
                _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
                code, out, err = _exec(cli,
                    f"{_cmd} << '__CADDY__'\n{CADDY_SCRIPT}\n__CADDY__",
                    timeout=300)
                if code != 0:
                    _log(f"[2.4] ❌ Caddy: {err[:300]}")
                    results['caddy'] = False
                else:
                    _, ver_out, _ = _exec(cli,
                        "/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || echo ''",
                        timeout=10)
                    ver = ver_out.strip().splitlines()[0] if ver_out.strip() else None
                    with lock:
                        server.naiveproxy_installed = True
                        if ver:
                            server.caddy_version = ver
                        db.add(server); db.commit()
                    _log(f"[2.4] ✅ Caddy + forwardproxy установлен{(' (' + ver + ')') if ver else ''}")
                    results['caddy'] = True
                cli.close()
            except Exception as e:
                _log(f"[2.4] ❌ Caddy: исключение: {e}")
                results['caddy'] = False

        # ── Запускаем потоки и ждём завершения ──────────────────────────────
        threads = [
            threading.Thread(target=install_xray,  name="install_xray",  daemon=True),
            threading.Thread(target=install_awg,   name="install_awg",   daemon=True),
            threading.Thread(target=install_caddy, name="install_caddy", daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=360)   # максимум 6 мин на весь блок параллельной установки

        # Итог
        ok_count = sum(1 for k in ('xray', 'awg', 'caddy') if results.get(k))
        _update_setup(db, server,
            log_line=f"[2] ✅ Установка компонентов: {ok_count}/3 успешно")

        # ── 2.5 WARP (все серверы: RU и EU) ────────────────────────────────────
        # WARP на EU: fallback для ресурсов, заблокированных на EU-выходе.
        # WARP на RU: fallback когда EU-сервер недоступен (каскад).
        _update_setup(db, server, log_line="[2.5] Установка WARP...")
        from app.services.deploy_service import install_warp
        ok, msg = install_warp(server, db=db)
        if ok:
            server.warp_installed = True
            # msg теперь содержит версию (e.g. "warp-cli 2026.3.846.0")
            if msg and not msg.startswith("WARP install failed"):
                server.warp_version = msg
            db.add(server); db.commit()
            _update_setup(db, server, log_line=f"[2.5] ✅ WARP установлен ({msg})")
        else:
            _update_setup(db, server, log_line=f"[2.5] ⚠️ WARP: {msg} (не критично)")

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
    # ★ ОПТИМИЗАЦИЯ 3: batch-скрипты вместо ~15 отдельных SSH round-trip
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step3", log_line="[3] Настройка безопасности...")

    client = _connect(cur_ip, cur_port, cur_user,
                      password=cur_pass, private_key_pem=cur_key)

    sec_password_auth_disabled = False
    sec_fail2ban_active        = False
    sec_ufw_active             = False
    sec_ssh_key_set            = False

    try:
        # ── 3.1-3.4 BATCH: Fail2Ban + UFW + пользователь ────────────────────
        # Вместо 10+ отдельных _se() вызовов — один скрипт
        # Экономия: ~10 SSH round-trips × ~150ms = ~1.5 сек + нет промежуточных lock
        _update_setup(db, server, log_line="[3.1] Настройка Fail2Ban, UFW и пользователя...")

        new_user_name = _gen_username() if is_eu else cur_user
        _current_ssh_port = cur_port

        # Диапазон UDP-портов для AWG
        AWG_PORT_RANGE_START = 10000
        AWG_PORT_RANGE_END   = 65535

        SECURITY_BATCH = f"""#!/bin/bash
# Не используем set -e чтобы маркеры статуса всегда появлялись в выводе
ERRS=""

# ── apt upgrade критичных пакетов (уже установлены на шаге 2.0) ──────────
export DEBIAN_FRONTEND=noninteractive
apt-get install --only-upgrade -y -qq \
    -o DPkg::Lock::Timeout=30 \
    openssh-server openssl 2>/dev/null || true
echo "[3.1_OK]"

# ── Fail2Ban ──────────────────────────────────────────────────────────────
systemctl enable fail2ban 2>/dev/null || true
systemctl start  fail2ban 2>/dev/null || true
printf '[DEFAULT]\\nbantime=3600\\nfindtime=600\\nmaxretry=5\\n[sshd]\\nenabled=true\\n' \
    > /etc/fail2ban/jail.local
systemctl restart fail2ban 2>/dev/null || true
F2B_STATUS=$(systemctl is-active fail2ban 2>/dev/null || echo inactive)
echo "[3.3_STATUS=$F2B_STATUS]"

# ── UFW ───────────────────────────────────────────────────────────────────
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow {_current_ssh_port}/tcp
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow {AWG_PORT_RANGE_START}:{AWG_PORT_RANGE_END}/udp
{'ufw allow 2408/udp' if not is_eu else '# EU: no 2408'}
DEBIAN_FRONTEND=noninteractive ufw --force enable
UFW_STATUS=$(ufw status 2>/dev/null | head -1 || echo unknown)
echo "[3.4_STATUS=$UFW_STATUS]"

# ── Новый пользователь (только EU) ───────────────────────────────────────
{'NEW_USER=' + new_user_name if is_eu else 'NEW_USER=' + cur_user}
if [ "$NEW_USER" != "{cur_user}" ]; then
    id "$NEW_USER" &>/dev/null || useradd -m -s /bin/bash "$NEW_USER"
    usermod -aG sudo "$NEW_USER" 2>/dev/null || true
    # NOPASSWD + !requiretty чтобы sudo -n работал в non-interactive SSH (paramiko)
    printf '%s ALL=(ALL) NOPASSWD:ALL\nDefaults:%s !requiretty\n' "$NEW_USER" "$NEW_USER" \
        > /etc/sudoers.d/"$NEW_USER"
    chmod 440 /etc/sudoers.d/"$NEW_USER"
    mkdir -p /home/"$NEW_USER"/.ssh && chmod 700 /home/"$NEW_USER"/.ssh
    cp ~/.ssh/authorized_keys /home/"$NEW_USER"/.ssh/authorized_keys 2>/dev/null || true
    chown -R "$NEW_USER":"$NEW_USER" /home/"$NEW_USER"/.ssh
    echo "[3.5_USER_CREATED=$NEW_USER]"
else
    echo "[3.5_USER_EXISTING=$NEW_USER]"
fi

echo "[BATCH_DONE]"
"""
        _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out, err = _exec(client,
            f"{_cmd} << '__SEC__'\n{SECURITY_BATCH}\n__SEC__",
            timeout=120)

        # Разбираем маркеры вывода
        if "[3.1_OK]" in out:
            _update_setup(db, server, log_line="[3.1] ✅ Критичные пакеты обновлены")
        else:
            _update_setup(db, server, log_line="[3.1] ⚠️ apt upgrade: проблема (некритично)")

        for ln in out.splitlines():
            if "[3.3_STATUS=" in ln:
                status_val = ln.split("=", 1)[1].rstrip("]").strip()
                sec_fail2ban_active = (status_val == "active")
                icon = "✅" if sec_fail2ban_active else "⚠️"
                _update_setup(db, server, log_line=f"[3.3] {icon} Fail2Ban: {status_val}")
            elif "[3.4_STATUS=" in ln:
                status_val = ln.split("=", 1)[1].rstrip("]").strip()
                sec_ufw_active = ("active" in status_val.lower())
                icon = "✅" if sec_ufw_active else "⚠️"
                _update_setup(db, server, log_line=f"[3.4] {icon} UFW: {status_val}")
            elif "[3.5_USER_CREATED=" in ln:
                created_name = ln.split("=", 1)[1].rstrip("]").strip()
                new_user = created_name
                _update_setup(db, server, log_line=f"[3.5] ✅ Пользователь {new_user} создан")
            elif "[3.5_USER_EXISTING=" in ln:
                new_user = cur_user
                _update_setup(db, server,
                    log_line=f"[3.5] ℹ️ RU-сервер: используем пользователя {cur_user}")

        if "[BATCH_DONE]" not in out:
            _update_setup(db, server,
                log_line=f"[3] ⚠️ batch-скрипт завершился с ошибкой: {err[:200]}")

        # ── 3.6 SSH-ключ Ed25519 ─────────────────────────────────────────────
        _update_setup(db, server, log_line="[3.6] Генерация SSH-ключа Ed25519...")
        new_priv, new_pub = _gen_ed25519_keypair()
        # Используем bash-скрипт с sudo чтобы создать .ssh в чужой home-директории
        _sd36 = "sudo -n " if use_sudo else ""
        KEY_SCRIPT = f"""#!/bin/bash
mkdir -p /home/{new_user}/.ssh
chmod 700 /home/{new_user}/.ssh
echo '{new_pub}' >> /home/{new_user}/.ssh/authorized_keys
chmod 600 /home/{new_user}/.ssh/authorized_keys
chown -R {new_user}:{new_user} /home/{new_user}/.ssh
echo KEY_WRITTEN
"""
        _kcmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, kout, err = _exec(client,
            f"{_kcmd} << '__KEY__'\n{KEY_SCRIPT}\n__KEY__",
            timeout=20)
        if code != 0 or "KEY_WRITTEN" not in kout:
            _update_setup(db, server, log_line=f"[3.6] ⚠️ Добавление ключа: {err[:200] or kout[:200]}")
        else:
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

        # ── 3.7-3.8 BATCH: смена пароля + отключение password auth ──────────
        _update_setup(db, server, log_line="[3.7] Смена пароля и отключение парольной аутентификации...")
        new_password = _gen_password()
        _sd = "sudo -n " if use_sudo else ""

        PASSWD_AUTH_SCRIPT = f"""#!/bin/bash
# Меняем пароль
echo '{new_user}:{new_password}' | {'sudo -n chpasswd' if use_sudo else 'chpasswd'}
echo "[3.7_OK]"

# Отключаем password auth во всех конфигах SSH (включая cloud-init drop-in)
{_sd}sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || \
    {_sd}bash -c 'echo PasswordAuthentication no >> /etc/ssh/sshd_config'
for f in /etc/ssh/sshd_config.d/*.conf; do
    [ -f "$f" ] && {_sd}sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' "$f"
done
{_sd}systemctl reload sshd 2>/dev/null || {_sd}systemctl reload ssh 2>/dev/null || true
echo "[3.8_OK]"
"""
        _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        code, out2, err2 = _exec(client,
            f"{_cmd} << '__PA__'\n{PASSWD_AUTH_SCRIPT}\n__PA__",
            timeout=30)
        if "[3.7_OK]" in out2:
            _update_setup(db, server, log_line="[3.7] ✅ Пароль обновлён")
            try:
                server.ssh_password_enc = encrypt_value(new_password)
            except AttributeError:
                pass
        else:
            _update_setup(db, server, log_line=f"[3.7] ⚠️ Смена пароля: {err2[:150]}")
        if "[3.8_OK]" in out2:
            sec_password_auth_disabled = True
            _update_setup(db, server,
                log_line="[3.8] ✅ Парольная аутентификация отключена")
        else:
            _update_setup(db, server, log_line=f"[3.8] ⚠️ Отключение password auth: {err2[:150]}")

        # ── 3.9 Смена SSH-порта ───────────────────────────────────────────────
        # ★ ОПТИМИЗАЦИЯ 4: polling вместо фиксированного sleep(8)
        _update_setup(db, server, log_line="[3.9] Смена SSH-порта...")
        new_port = _gen_ssh_port()

        # Шаги A-D: открываем новый порт, меняем конфиг, рестартуем — одним batch
        _ufw_cmd = "sudo -n ufw" if use_sudo else "ufw"
        PORT_CHANGE_SCRIPT = f"""#!/bin/bash
{_ufw_cmd} allow {new_port}/tcp 2>/dev/null || true
sed -i '/^#*Port /d' /etc/ssh/sshd_config
echo 'Port {new_port}' >> /etc/ssh/sshd_config
systemctl disable ssh.socket 2>/dev/null || true
systemctl stop    ssh.socket 2>/dev/null || true
rm -f /etc/systemd/system/ssh.socket.d/port.conf 2>/dev/null
systemctl daemon-reload
nohup bash -c 'sleep 2 && systemctl restart ssh.service 2>/dev/null || systemctl restart sshd 2>/dev/null' \
    > /tmp/sshd_restart.log 2>&1 &
echo "[PORT_CHANGE_SENT]"
"""
        _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        _exec(client,
            f"{_cmd} << '__PC__'\n{PORT_CHANGE_SCRIPT}\n__PC__",
            timeout=15)

        # Шаг E: polling вместо sleep — проверяем каждые 2 сек, максимум 30 сек
        _update_setup(db, server, log_line=f"[3.9] ⏳ Ожидание SSH на порту {new_port}...")
        port_ok = False
        for attempt in range(15):    # 15 × 2 сек = 30 сек максимум
            time.sleep(2)
            try:
                test_cli = _connect(cur_ip, new_port, cur_user,
                                    private_key_pem=cur_key, timeout=5)
                old_ssh_port = cur_port
                _ufw_del = "sudo -n ufw" if use_sudo else "ufw"
                _exec(test_cli,
                    f"{_ufw_del} delete allow {old_ssh_port}/tcp 2>/dev/null || true && "
                    f"{_ufw_del} delete allow 22/tcp 2>/dev/null || true",
                    timeout=10)
                test_cli.close()
                cur_port = new_port
                port_ok = True
                _update_setup(db, server,
                    log_line=f"[3.9] ✅ SSH-порт изменён на {new_port} (попытка {attempt+1})")
                break
            except Exception:
                if attempt == 7:    # ~16 сек — логируем промежуточный статус
                    _update_setup(db, server,
                        log_line=f"[3.9] ⏳ Порт {new_port} ещё не готов, ждём...")

        if not port_ok:
            _update_setup(db, server, log_line="[3.9] ⚠️ Новый порт не ответил — откат на порт 22...")
            try:
                rb = _connect(cur_ip, 22, cur_user, private_key_pem=cur_key, timeout=10)
                _exec(rb,
                    "sed -i '/^Port /d' /etc/ssh/sshd_config && "
                    "echo 'Port 22' >> /etc/ssh/sshd_config && "
                    "systemctl daemon-reload && "
                    "systemctl enable ssh.socket 2>/dev/null || true && "
                    "systemctl restart ssh.service 2>/dev/null || "
                    "systemctl restart sshd 2>/dev/null || true",
                    timeout=20)
                rb.close()
                cur_port = 22
                _update_setup(db, server, log_line="[3.9] ⚠️ Откат выполнен — SSH на порту 22")
            except Exception as rb_e:
                _update_setup(db, server, log_line=f"[3.9] ⚠️ Откат не удался: {rb_e}")

        # Сохраняем финальные credentials
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

        # Переподключаемся для шагов 4-5
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

        # Обновляем use_sudo: после смены пользователя (vpnadmin*) нужен sudo
        use_sudo = (cur_user != "root")

    except Exception as e:
        _update_setup(db, server, log_line=f"[3] ⚠️ Шаг безопасности упал: {e}")
        try:
            client.close()
        except Exception:
            pass
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

        # Обновляем use_sudo при fallback-переподключении
        use_sudo = (cur_user != "root")

    _update_setup(db, server, log_line="[3] ✅ Настройка безопасности завершена")

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 4 — Сбор информации о сервере + security flags в БД
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step4", log_line="[4] Сбор информации о сервере...")
    try:
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
                        log_line=f"[4] ✅ Страна: {_geo['country']} ({server.country})")
                else:
                    _update_setup(db, server, log_line="[4] ⚠️ Страна не определена")
            except Exception as _ge:
                _update_setup(db, server, log_line=f"[4] ⚠️ Гео-запрос не удался: {_ge}")

        # Собираем всё за один SSH-вызов
        # INFO_SCRIPT запускается через «sudo -n bash -s» (use_sudo=True) или «bash -s» (root).
        # Внутри скрипта мы уже root-пользователь (через sudo), поэтому вложенный sudo не нужен —
        # просто вызываем ufw напрямую.
        INFO_SCRIPT = f"""#!/bin/bash
echo "TZ=$(cat /etc/timezone 2>/dev/null || timedatectl | grep 'Time zone' | awk '{{print $3}}')"
echo "XRAY=$(xray version 2>/dev/null | head -1 || echo '')"
echo "CADDY=$(/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || /usr/local/bin/caddy version 2>/dev/null | head -1 || echo '')"
echo "AWG=$(awg --version 2>/dev/null | head -1 || echo '')"
echo "F2B=$(systemctl is-active fail2ban 2>/dev/null || echo inactive)"
echo "UFW=$(ufw status 2>/dev/null | head -1 || echo unknown)"
echo "PWAUTH=$(grep -rE '^PasswordAuthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null || echo '')"
"""
        _cmd = ("sudo -n bash -s" if use_sudo else "bash -s")
        _, info_out, _ = _exec(client,
            f"{_cmd} << '__INFO__'\n{INFO_SCRIPT}\n__INFO__",
            timeout=30)

        # Добавляем WARP для RU отдельно (warp-cli может зависнуть)
        warp_v = None
        if not is_eu:
            _, warp_raw, _ = _exec(client,
                "warp-cli --version 2>/dev/null | head -1 || echo ''",
                timeout=10)
            warp_v = warp_raw.strip()[:50] or None

        # Парсим вывод
        info = {}
        for ln in info_out.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                info[k.strip()] = v.strip()

        server.server_timezone = info.get("TZ") or None
        server.xray_version    = (info.get("XRAY") or "")[:50] or None
        server.caddy_version   = (info.get("CADDY") or "")[:50] or None
        _awg_v_raw             = info.get("AWG") or ""
        server.awg_version     = _awg_v_raw[:50] if _awg_v_raw else None
        if not is_eu:
            server.warp_version = warp_v

        # Security flags
        fb_first  = info.get("F2B", "inactive")
        ufw_first = info.get("UFW", "unknown")
        pw_lines  = [l.strip().lower()
                     for l in (info.get("PWAUTH") or "").splitlines()
                     if "passwordauthentication" in l.lower()]
        sec_fail2ban_active        = (fb_first == "active")
        sec_ufw_active             = ("active" in ufw_first.lower())
        sec_password_auth_disabled = bool(pw_lines) and all("no" in l for l in pw_lines)
        sec_ssh_key_set            = bool(cur_key)

        server.sec_fail2ban       = sec_fail2ban_active
        server.sec_ufw            = sec_ufw_active
        server.sec_password_login = not sec_password_auth_disabled
        server.sec_ssh_key        = sec_ssh_key_set

        server.ssh_user_actual = cur_user
        server.ssh_port_actual = cur_port
        server.ssh_user = cur_user
        server.ssh_port = cur_port

        if cur_key:
            server.ssh_key = cur_key
            try:
                server.ssh_private_key_enc = encrypt_value(cur_key)
            except Exception as _e:
                _update_setup(db, server, log_line=f"[4] ⚠️ Не удалось зашифровать SSH-ключ: {_e}")
                server.ssh_key = cur_key
        if cur_pass:
            try:
                server.ssh_password_enc = encrypt_value(cur_pass)
                server.ssh_password = None
            except Exception as _e:
                _update_setup(db, server, log_line=f"[4] ⚠️ Не удалось зашифровать пароль: {_e}")

        db.add(server); db.commit()

        if not server.server_timezone and not server.xray_version and not server.awg_version:
            _update_setup(db, server, status="failed",
                          error="SSH-соединение по новым credentials не работает",
                          log_line="[4] ❌ Данные не прочитаны — проверьте SSH-доступ")
            server.status = ServerStatus.NOT_CONFIGURED
            db.add(server); db.commit()
            try: client.close()
            except Exception: pass
            return

        _update_setup(db, server, log_line="[4] ✅ Информация собрана")
        _update_setup(db, server, log_line=f"[4]    Timezone  : {server.server_timezone or '—'}")
        _update_setup(db, server, log_line=f"[4]    Xray      : {server.xray_version    or '—'}")
        _update_setup(db, server, log_line=f"[4]    AWG       : {server.awg_version     or 'не установлен'}")
        _update_setup(db, server, log_line=f"[4]    Caddy NP  : {server.caddy_version   or '—'}")
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

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 4.5 — Auto-DNS: создаём A-запись и устанавливаем server.domain
        # (только для EU-серверов без домена)
        # ═══════════════════════════════════════════════════════════════════════
        if is_eu and not server.domain:
            _update_setup(db, server, log_line="[4.5] 🌐 EU-сервер без домена — создаём DNS A-запись...")
            try:
                _auto_assign_domain(db, server)
                if server.domain:
                    _update_setup(db, server,
                        log_line=f"[4.5] ✅ Домен назначен: {server.domain}")
                    # Открываем порт 80 для Let's Encrypt ACME challenge
                    try:
                        _se(client, "ufw allow 80/tcp 2>/dev/null || true", use_sudo, timeout=10)
                        _update_setup(db, server, log_line="[4.5] ✅ UFW: порт 80 открыт для ACME")
                    except Exception:
                        pass
                else:
                    _update_setup(db, server,
                        log_line="[4.5] ⚠️ Домен не назначен — добавьте домен в разделе Domains")
            except Exception as _dns_e:
                _update_setup(db, server,
                    log_line=f"[4.5] ⚠️ Auto-DNS не удался: {_dns_e} (не критично)")
        elif is_eu and server.domain:
            _update_setup(db, server,
                log_line=f"[4.5] ✅ Домен уже установлен: {server.domain}")
            # Убеждаемся что порт 80 открыт для ACME
            try:
                _se(client, "ufw allow 80/tcp 2>/dev/null || true", use_sudo, timeout=10)
            except Exception:
                pass

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
    # ШАГ 5 — Финальная проверка
    # ═══════════════════════════════════════════════════════════════════════════
    _update_setup(db, server, step="step5", log_line="[5] Финальная проверка...")

    critical_ok = True

    checks = [
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
            None,
            False),
        ("NaiveProxy",
            "test -f /usr/local/bin/caddy-naive || which caddy-naive",
            None,
            False),
        ("Fail2Ban",
            "which fail2ban-server || dpkg -l fail2ban 2>/dev/null | grep -q '^ii'",
            "systemctl is-active fail2ban 2>/dev/null || echo inactive",
            False),
        ("UFW",
            "which ufw || dpkg -l ufw 2>/dev/null | grep -q '^ii'",
            "sudo -n bash -c 'ufw status 2>/dev/null | head -1' 2>/dev/null || ufw status 2>/dev/null | head -1 || echo unknown",
            False),
    ]
    if not is_eu:
        checks.append((
            "WARP",
            "which warp-cli || dpkg -l cloudflare-warp 2>/dev/null | grep -q '^ii'",
            "warp-cli status 2>/dev/null || echo 'warp-status-failed'",
            False,
        ))

    for name, install_cmd, run_cmd, is_critical in checks:
        try:
            code_i, _, _ = _exec(client, _s(install_cmd, use_sudo), timeout=10)
            installed = (code_i == 0)

            if not installed:
                icon = "❌" if is_critical else "⚠️"
                _update_setup(db, server, log_line=f"[5] {icon} {name}: не установлен")
                if is_critical:
                    critical_ok = False
                continue

            if run_cmd is None:
                _update_setup(db, server,
                    log_line=f"[5] ✅ {name}: установлен, будет запущен при настройке подключений")
                continue

            code_r, out_r, _ = _exec(client, _s(run_cmd, use_sudo), timeout=15)
            out_lower = out_r.lower()
            first_line = next(
                (l.strip() for l in out_r.splitlines() if l.strip()), ""
            ).lower()
            display = out_r.splitlines()[0].strip() if out_r.strip() else "(нет вывода)"

            if name == "WARP":
                if "unable" in out_lower or "warp-status-failed" in out_lower or not out_r.strip():
                    _exec(client,
                        "sudo -n systemctl start warp-svc 2>/dev/null || "
                        "systemctl start warp-svc 2>/dev/null || true",
                        timeout=15)
                    import time as _time; _time.sleep(3)
                    _, out_r2, _ = _exec(client,
                        "warp-cli status 2>/dev/null || echo 'warp-status-failed'",
                        timeout=10)
                    if out_r2.strip():
                        out_r = out_r2
                        out_lower = out_r.lower()
                        display = out_r.splitlines()[0].strip()
                is_up   = "connected" in out_lower or "status: connected" in out_lower
                is_down = ("disconnected" in out_lower or "unable" in out_lower
                           or "warp-status-failed" in out_lower or not out_r.strip())
            else:
                is_up   = (first_line in ("active", "alive")
                           or "active" in first_line
                           or "connected" in first_line)
                is_down = ("inactive" in first_line or "failed" in first_line
                           or first_line in ("activating", "deactivating"))

            if name == "SSH":
                if "alive" in first_line or code_r == 0:
                    _update_setup(db, server, log_line="[5] ✅ SSH: установлен и доступен")
                else:
                    _update_setup(db, server, log_line=f"[5] ❌ SSH: недоступен ({display})")
                    critical_ok = False
            elif is_up:
                _update_setup(db, server, log_line=f"[5] ✅ {name}: установлен и запущен")
            elif is_down:
                icon = "❌" if is_critical else "⚠️"
                _update_setup(db, server,
                    log_line=f"[5] {icon} {name}: установлен, не запущен ({display})")
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
