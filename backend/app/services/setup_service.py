"""
Setup Service — автоматическая настройка сервера при создании.

Шаги:
  1. Проверка подключения
  2. Настройка безопасности (apt upgrade, fail2ban, ufw, смена пользователя,
     генерация SSH-ключа, смена пароля, отключение password auth, смена порта)
  3. Установка стека (xray, awg, naiveproxy+caddy, warp для RU)
  4. Сбор информации о сервере
  5. Финальная проверка
"""
import io
import json
import logging
import random
import secrets
import string
import time
from typing import Optional, Tuple

import paramiko
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.server import Server, ServerRole, ServerStatus
from app.services.ssh_service import SSHClient

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
    return random.randint(10000, 65000)


def _gen_username() -> str:
    suffix = random.randint(1000, 9999)
    return f"vpnadmin{suffix}"


def _gen_ed25519_keypair() -> Tuple[str, str]:
    """Генерирует пару Ed25519, возвращает (private_pem, public_openssh)."""
    key = paramiko.Ed25519Key.generate()
    priv_buf = io.StringIO()
    key.write_private_key(priv_buf)
    priv_pem = priv_buf.getvalue()
    pub_openssh = f"ssh-ed25519 {key.get_base64()} vpnadmin"
    return priv_pem, pub_openssh


# ─────────────────────────────────────────────────────────────────────────────
# Хелпер для подключения с актуальными credentials
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
    elif password:
        kwargs["password"] = password
        kwargs["look_for_keys"] = False
    client.connect(**kwargs)
    return client


def _exec(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> Tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return code, out, err


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
    db.add(server)
    db.commit()

    # Текущие credentials (могут обновляться по ходу)
    cur_ip   = server.ip
    cur_port = server.ssh_port or 22
    cur_user = server.ssh_user or "root"
    cur_pass = server.ssh_password
    cur_key  = server.ssh_key      # может быть None для EU
    is_eu    = str(server.role).upper() in ("EU", "SERVERROLE.EU")

    # ── Шаг 1: Проверка подключения ──────────────────────────────────────────
    _update_setup(db, server, step="step1", log_line="[1] Проверка подключения...")
    try:
        client = _connect(cur_ip, cur_port, cur_user,
                          password=cur_pass, private_key_pem=cur_key)
        code, out, _ = _exec(client, "echo OK && id")
        client.close()
        if "OK" not in out:
            raise RuntimeError("Сервер не ответил на echo OK")
        _update_setup(db, server, log_line=f"[1] ✅ Подключение установлено. {out.strip()}")
    except Exception as e:
        _update_setup(db, server, status="failed", error=str(e),
                      log_line=f"[1] ❌ Ошибка подключения: {e}")
        server.status = ServerStatus.NOT_CONFIGURED
        db.add(server); db.commit()
        return  # критический шаг — останавливаемся

    # ── Шаг 2: Настройка безопасности ────────────────────────────────────────
    _update_setup(db, server, step="step2", log_line="[2] Настройка безопасности...")

    client = _connect(cur_ip, cur_port, cur_user,
                      password=cur_pass, private_key_pem=cur_key)
    try:
        # 2.1 Обновление системы
        _update_setup(db, server, log_line="[2.1] apt update + upgrade...")
        code, _, err = _exec(client,
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq && "
            "apt-get install -y -qq unattended-upgrades && "
            "echo 'Unattended-Upgrade::Automatic-Reboot \"false\";' "
            "> /etc/apt/apt.conf.d/99auto-upgrades",
            timeout=600)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.1] ⚠️ apt upgrade завершился с ошибкой: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.1] ✅ Система обновлена")

        # 2.2 Fail2Ban
        _update_setup(db, server, log_line="[2.2] Установка Fail2Ban...")
        code, _, err = _exec(client,
            "apt-get install -y -qq fail2ban && "
            "systemctl enable fail2ban && systemctl start fail2ban && "
            "cat > /etc/fail2ban/jail.local << 'EOF'\n"
            "[DEFAULT]\nbantime = 3600\nfindtime = 600\nmaxretry = 5\n\n"
            "[sshd]\nenabled = true\nEOF\n"
            "systemctl restart fail2ban", timeout=120)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.2] ⚠️ Fail2Ban: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.2] ✅ Fail2Ban установлен")

        # 2.3 UFW
        _update_setup(db, server, log_line="[2.3] Настройка UFW...")
        ufw_cmds = (
            "apt-get install -y -qq ufw && "
            "ufw --force reset && "
            "ufw default deny incoming && "
            "ufw default allow outgoing && "
            "ufw allow 22/tcp && "      # временно — до смены порта
            "ufw allow 80/tcp && "
            "ufw allow 443/tcp && "
            "ufw allow 51820/udp"
        )
        if not is_eu:
            ufw_cmds += " && ufw allow 2408/udp"
        ufw_cmds += " && echo 'y' | ufw enable"
        code, _, err = _exec(client, ufw_cmds, timeout=120)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.3] ⚠️ UFW: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.3] ✅ UFW настроен")

        # 2.4 Смена пользователя
        _update_setup(db, server, log_line="[2.4] Создание нового SSH-пользователя...")
        new_user = _gen_username()
        create_user_cmd = (
            f"id {new_user} &>/dev/null || useradd -m -s /bin/bash {new_user} && "
            f"usermod -aG sudo {new_user} && "
            f"echo '{new_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{new_user} && "
            f"chmod 440 /etc/sudoers.d/{new_user} && "
            f"mkdir -p /home/{new_user}/.ssh && "
            f"chmod 700 /home/{new_user}/.ssh && "
            # Копируем authorized_keys от текущего пользователя
            f"cp ~/.ssh/authorized_keys /home/{new_user}/.ssh/authorized_keys 2>/dev/null || true && "
            f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh && "
            f"echo created"
        )
        code, out, err = _exec(client, create_user_cmd, timeout=60)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.4] ⚠️ Не удалось создать пользователя: {err[:200]}")
        else:
            _update_setup(db, server, log_line=f"[2.4] ✅ Пользователь {new_user} создан")
            # Блокируем старого пользователя только если он не root
            if cur_user != "root":
                _exec(client, f"usermod -L {cur_user}", timeout=30)

        # 2.5 Генерация нового SSH-ключа
        _update_setup(db, server, log_line="[2.5] Генерация SSH-ключа...")
        new_priv, new_pub = _gen_ed25519_keypair()
        add_key_cmd = (
            f"mkdir -p /home/{new_user}/.ssh && "
            f"echo '{new_pub}' >> /home/{new_user}/.ssh/authorized_keys && "
            f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh && "
            f"chmod 600 /home/{new_user}/.ssh/authorized_keys"
        )
        code, _, err = _exec(client, add_key_cmd, timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.5] ⚠️ Добавление ключа: {err[:200]}")
        else:
            # Проверяем подключение по новому ключу
            try:
                test_cli = _connect(cur_ip, cur_port, new_user, private_key_pem=new_priv)
                _exec(test_cli, "echo KEY_OK")
                test_cli.close()
                cur_user = new_user
                cur_key  = new_priv
                cur_pass = None
                _update_setup(db, server, log_line="[2.5] ✅ SSH-ключ сгенерирован и проверен")
            except Exception as e:
                _update_setup(db, server, log_line=f"[2.5] ⚠️ Ключ создан, но проверка не прошла: {e}")

        # 2.6 Смена пароля
        _update_setup(db, server, log_line="[2.6] Смена пароля...")
        new_password = _gen_password()
        code, _, err = _exec(client,
            f"echo '{new_user}:{new_password}' | chpasswd", timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.6] ⚠️ Смена пароля: {err[:200]}")
        else:
            _update_setup(db, server, log_line="[2.6] ✅ Пароль обновлён")
            server.ssh_password_enc = encrypt_value(new_password)

        # 2.7 Отключение password auth (для EU обязательно, для RU если включено)
        _update_setup(db, server, log_line="[2.7] Отключение парольной аутентификации SSH...")
        code, out, _ = _exec(client,
            "grep -E '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'not_set'")
        already_off = "no" in out.lower()
        if not already_off:
            code, _, err = _exec(client,
                "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && "
                "grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || "
                "echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config && "
                "systemctl reload sshd || systemctl reload ssh", timeout=30)
            if code != 0:
                _update_setup(db, server, log_line=f"[2.7] ⚠️ Отключение password auth: {err[:200]}")
            else:
                _update_setup(db, server, log_line="[2.7] ✅ Парольная аутентификация отключена")
        else:
            _update_setup(db, server, log_line="[2.7] ✅ Парольная аутентификация уже отключена")

        # 2.8 Смена SSH-порта
        _update_setup(db, server, log_line="[2.8] Смена SSH-порта...")
        new_port = _gen_ssh_port()
        code, _, err = _exec(client,
            f"sed -i 's/^#*Port .*/Port {new_port}/' /etc/ssh/sshd_config && "
            f"grep -q '^Port' /etc/ssh/sshd_config || echo 'Port {new_port}' >> /etc/ssh/sshd_config && "
            f"ufw allow {new_port}/tcp && "
            f"ufw delete allow 22/tcp && "
            f"systemctl restart sshd || systemctl restart ssh", timeout=30)
        if code != 0:
            _update_setup(db, server, log_line=f"[2.8] ⚠️ Смена порта: {err[:200]}")
        else:
            # Проверяем подключение на новый порт
            time.sleep(3)
            try:
                test_cli = _connect(cur_ip, new_port, cur_user, private_key_pem=cur_key)
                _exec(test_cli, "echo PORT_OK")
                test_cli.close()
                cur_port = new_port
                server.ssh_port_actual = new_port
                _update_setup(db, server, log_line=f"[2.8] ✅ SSH-порт изменён на {new_port}")
            except Exception as e:
                _update_setup(db, server, log_line=f"[2.8] ⚠️ Порт изменён, но проверка не прошла: {e}")

        # Сохраняем актуальные credentials в БД
        server.ssh_user_actual = cur_user
        if cur_key:
            server.ssh_private_key_enc = encrypt_value(cur_key)
        db.add(server); db.commit()

        # Переподключаемся с актуальными данными
        client.close()
        client = _connect(cur_ip, cur_port, cur_user, private_key_pem=cur_key)

    except Exception as e:
        _update_setup(db, server, log_line=f"[2] ⚠️ Шаг безопасности упал: {e}")
        try:
            client.close()
        except Exception:
            pass
        client = _connect(cur_ip, cur_port, cur_user,
                          password=cur_pass, private_key_pem=cur_key)

    _update_setup(db, server, log_line="[2] ✅ Настройка безопасности завершена")

    # ── Шаг 3: Установка стека ────────────────────────────────────────────────
    _update_setup(db, server, step="step3", log_line="[3] Установка стека...")

    # 3.1 Xray-core
    _update_setup(db, server, log_line="[3.1] Установка Xray-core...")
    from app.services.deploy_service import install_xray, generate_reality_keys

    # Создаём временный объект сервера с актуальными credentials для deploy_service
    server.ssh_user     = cur_user
    server.ssh_port     = cur_port
    server.ssh_key      = cur_key
    server.ssh_password = None
    db.add(server); db.commit()

    ok, msg = install_xray(server)
    if ok:
        _update_setup(db, server, log_line="[3.1] ✅ Xray установлен")
        server.xray_installed = True
        # Генерируем Reality-ключи
        pub, priv = generate_reality_keys(server)
        if pub:
            server.xray_public_key = pub
            _update_setup(db, server, log_line=f"[3.1] ✅ Reality-ключи сгенерированы")
    else:
        _update_setup(db, server, log_line=f"[3.1] ❌ Xray: {msg}")

    # 3.2 AmneziaWG
    _update_setup(db, server, log_line="[3.2] Установка AmneziaWG...")
    AWG_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing AmneziaWG..."
apt-get update -qq
apt-get install -y -qq software-properties-common
add-apt-repository -y ppa:amnezia/ppa 2>/dev/null || true
apt-get update -qq
apt-get install -y -qq amneziawg amneziawg-tools
modprobe amneziawg 2>/dev/null || true
echo "[+] AmneziaWG installed"
"""
    code, out, err = _exec(client, AWG_INSTALL_SCRIPT, timeout=300)
    if code != 0:
        _update_setup(db, server, log_line=f"[3.2] ❌ AWG: {err[:300]}")
    else:
        server.awg_installed = True
        # Генерируем серверные ключи AWG
        code2, keys_out, _ = _exec(client,
            "awg genkey | tee /tmp/awg_server.key | awg pubkey > /tmp/awg_server.pub && "
            "cat /tmp/awg_server.pub")
        if code2 == 0:
            server.awg_server_public_key = keys_out.strip()
        _update_setup(db, server, log_line="[3.2] ✅ AmneziaWG установлен")

    # 3.3 NaiveProxy + Caddy
    _update_setup(db, server, log_line="[3.3] Установка NaiveProxy + Caddy...")
    NAIVE_INSTALL_SCRIPT = """#!/bin/bash
set -e
echo "[*] Installing Caddy + NaiveProxy..."
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-xcaddy-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/xcaddy/debian.deb.txt' > /etc/apt/sources.list.d/caddy-xcaddy.list
apt-get update -qq
apt-get install -y -qq xcaddy golang-go
xcaddy build --with github.com/caddyserver/forwardproxy@caddy2=github.com/klzgrad/forwardproxy@naive -o /usr/local/bin/caddy-naive
chmod +x /usr/local/bin/caddy-naive
mkdir -p /etc/caddy-naive
echo "[+] NaiveProxy + Caddy installed"
"""
    code, out, err = _exec(client, NAIVE_INSTALL_SCRIPT, timeout=600)
    if code != 0:
        _update_setup(db, server, log_line=f"[3.3] ❌ NaiveProxy: {err[:300]}")
    else:
        server.naiveproxy_installed = True
        _update_setup(db, server, log_line="[3.3] ✅ NaiveProxy + Caddy установлены")

        # Проверяем наличие свободного поддомена для NaiveProxy
        _try_link_naiveproxy_subdomain(db, server, client, is_eu)

    # 3.4 WARP (только RU)
    if not is_eu:
        _update_setup(db, server, log_line="[3.4] Установка WARP...")
        from app.services.deploy_service import install_warp
        ok, msg = install_warp(server)
        if ok:
            server.warp_installed = True
            _update_setup(db, server, log_line="[3.4] ✅ WARP установлен")
        else:
            _update_setup(db, server, log_line=f"[3.4] ❌ WARP: {msg}")

    db.add(server); db.commit()
    _update_setup(db, server, log_line="[3] ✅ Установка стека завершена")

    # ── Шаг 4: Сбор информации ────────────────────────────────────────────────
    _update_setup(db, server, step="step4", log_line="[4] Сбор информации о сервере...")
    try:
        _, tz_out,  _ = _exec(client, "cat /etc/timezone 2>/dev/null || timedatectl | grep 'Time zone' | awk '{print $3}'")
        _, xray_v,  _ = _exec(client, "xray version 2>/dev/null | head -1 || echo ''")
        _, caddy_v, _ = _exec(client, "/usr/local/bin/caddy-naive version 2>/dev/null | head -1 || echo ''")
        _, awg_v,   _ = _exec(client, "awg --version 2>/dev/null | head -1 || echo ''")

        server.server_timezone = tz_out.strip() or None
        server.xray_version    = xray_v.strip()[:50] or None
        server.caddy_version   = caddy_v.strip()[:50] or None
        server.awg_version     = awg_v.strip()[:50] or None

        if not is_eu:
            _, warp_v, _ = _exec(client, "warp-cli --version 2>/dev/null | head -1 || echo ''")
            server.warp_version = warp_v.strip()[:50] or None

        db.add(server); db.commit()
        _update_setup(db, server, log_line="[4] ✅ Информация собрана")
    except Exception as e:
        _update_setup(db, server, log_line=f"[4] ⚠️ Сбор информации: {e}")

    # ── Шаг 5: Финальная проверка ─────────────────────────────────────────────
    _update_setup(db, server, step="step5", log_line="[5] Финальная проверка...")
    all_ok = True

    checks = [
        ("SSH",      "echo ALIVE"),
        ("Xray",     "systemctl is-active xray"),
        ("AWG",      "systemctl is-active awg-quick@wg0 2>/dev/null || systemctl is-active amneziawg@wg0 2>/dev/null || echo inactive"),
        ("Caddy",    "systemctl is-active caddy-naive 2>/dev/null || echo inactive"),
        ("Fail2Ban", "systemctl is-active fail2ban"),
        ("UFW",      "ufw status | head -1"),
    ]
    if not is_eu:
        checks.append(("WARP", "warp-cli status 2>/dev/null | head -1 || echo unknown"))

    for name, cmd in checks:
        try:
            code, out, _ = _exec(client, cmd, timeout=15)
            out_clean = out.strip().lower()
            is_critical = name in ("SSH", "Xray")
            if "active" in out_clean or "alive" in out_clean or "connected" in out_clean:
                _update_setup(db, server, log_line=f"[5] ✅ {name}: {out.strip()}")
            elif "inactive" in out_clean or "failed" in out_clean:
                icon = "❌" if is_critical else "⚠️"
                _update_setup(db, server, log_line=f"[5] {icon} {name}: {out.strip()}")
                if is_critical:
                    all_ok = False
            else:
                _update_setup(db, server, log_line=f"[5] ⚠️ {name}: {out.strip()}")
        except Exception as e:
            _update_setup(db, server, log_line=f"[5] ⚠️ {name}: {e}")

    client.close()

    # Финальный статус
    if all_ok:
        server.setup_status = "done"
        server.status       = ServerStatus.ONLINE
        _update_setup(db, server, log_line="[setup] ✅ Настройка завершена успешно")
    else:
        server.setup_status = "failed"
        server.status       = ServerStatus.NOT_CONFIGURED
        _update_setup(db, server, log_line="[setup] ❌ Настройка завершена с ошибками")

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
            _update_setup(db, server,
                          log_line=f"[3.3] ⚠️ Нет свободного поддомена типа {stype} — NaiveProxy без домена")
            return

        domain = sub.full_domain
        server.naiveproxy_subdomain_id = sub.id
        sub.server_id = server.id
        db.add(sub); db.add(server); db.commit()
        _update_setup(db, server, log_line=f"[3.3] 🔗 Привязан поддомен {domain}")
    except Exception as e:
        _update_setup(db, server, log_line=f"[3.3] ⚠️ Автопривязка поддомена: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Получение статуса для API (polling)
# ─────────────────────────────────────────────────────────────────────────────

def get_setup_status(server: Server) -> dict:
    log_lines = (server.setup_log or "").strip().split("\n") if server.setup_log else []
    return {
        "setup_status": server.setup_status or "not_started",
        "setup_step":   server.setup_step,
        "setup_error":  server.setup_error,
        "log":          log_lines,
    }
