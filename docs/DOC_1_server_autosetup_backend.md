# Автонастройка серверов — Backend

## Обзор архитектуры

Автонастройка запускается как **background task** (FastAPI `BackgroundTasks`) при добавлении сервера.
Весь процесс реализован в `backend/app/services/setup_service.py`.

Логика разделена на **5 шагов**, прогресс пишется в БД (поля `setup_step`, `setup_status`, `setup_log`).
Фронтенд опрашивает endpoint `/servers/{id}/setup/status` каждые 2 секунды.

---

## Файлы

| Файл | Роль |
|------|------|
| `backend/app/services/setup_service.py` | Вся логика автонастройки |
| `backend/app/services/deploy_service.py` | `install_warp()`, `install_xray()` |
| `backend/app/api/v1/servers.py` | REST endpoints для управления setup |

---

## Поля модели Server (setup-related)

```python
# Прогресс и статус
setup_status: str        # None | "in_progress" | "done" | "failed"
setup_step:   str        # "step1" .. "step5"
setup_log:    str        # Многострочный лог (каждая строка "[N] текст")
setup_error:  str        # Текст критической ошибки при failed

# SSH-доступ (обновляются в ходе настройки)
ssh_user:          str   # Исходный пользователь (может быть root или fakeart)
ssh_user_actual:   str   # Итоговый пользователь после настройки
ssh_port:          int   # Исходный порт (обычно 22)
ssh_port_actual:   int   # Новый порт после смены
ssh_password:      str   # Открытый пароль (очищается после шифрования)
ssh_password_enc:  str   # Пароль, зашифрованный Fernet
ssh_key:           str   # Приватный ключ (открытый, очищается)
ssh_private_key_enc: str # Приватный ключ, зашифрованный Fernet

# Установленные компоненты
xray_installed:        bool
awg_installed:         bool
naiveproxy_installed:  bool
warp_installed:        bool   # только для RU
xray_public_key:       str    # Reality public key
awg_server_public_key: str
caddy_version:         str    # Здесь хранится версия NaiveProxy

# Security flags (заполняются на шаге 3)
sec_fail2ban:        bool
sec_ufw:             bool
sec_password_login:  bool     # True = вход по паролю включён
```

---

## API Endpoints

```python
# ── Запуск автонастройки ─────────────────────────────────────────────────────
POST /api/v1/servers/{server_id}/setup
# Запускает run_server_setup() как background task
# Если уже in_progress — возвращает {"success": False, "message": "Setup already in progress"}

# ── Polling статуса (используется фронтендом, каждые 2 сек) ─────────────────
GET /api/v1/servers/{server_id}/setup/status
# Ответ:
{
  "setup_status": "in_progress" | "done" | "failed",
  "setup_step":   "step1" | "step2" | "step3" | "step4" | "step5",
  "setup_error":  "текст ошибки или null",
  "log":          ["[1] строка 1", "[2] строка 2", ...]
}

# ── Повторный запуск ─────────────────────────────────────────────────────────
POST /api/v1/servers/{server_id}/setup/retry
# Сбрасывает setup_status/step/error/log → запускает заново

# ── Отмена и удаление сервера ────────────────────────────────────────────────
DELETE /api/v1/servers/{server_id}/setup/cancel
# Удаляет запись сервера из БД

# ── SSE-поток (не используется основным UI, резерв) ─────────────────────────
GET /api/v1/servers/{server_id}/setup-stream
# Server-Sent Events: каждые 1.5 сек отдаёт новые строки лога

# ── Получить расшифрованный пароль ───────────────────────────────────────────
GET /api/v1/servers/{server_id}/ssh-password
# Расшифровывает ssh_password_enc через Fernet и возвращает {"password": "..."}
```

Код endpoint'ов (`backend/app/api/v1/servers.py`, строки 426–530):

```python
from app.services.setup_service import decrypt_value, run_server_setup

@router.post("/{server_id}/setup")
def start_setup(server_id, background_tasks, db, _):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404)
    if getattr(server, "setup_status", None) == "in_progress":
        return {"success": False, "message": "Setup already in progress"}
    background_tasks.add_task(run_server_setup, server_id)
    return {"success": True, "message": "Setup started"}

@router.get("/{server_id}/setup/status")
def get_setup_status(server_id, db, _):
    server = server_service.get_server(db, server_id)
    log_raw = getattr(server, "setup_log", "") or ""
    log_lines = [l.strip() for l in log_raw.splitlines() if l.strip()]
    return {
        "setup_status": getattr(server, "setup_status", None),
        "setup_step":   getattr(server, "setup_step",   None),
        "setup_error":  getattr(server, "setup_error",  None),
        "log":          log_lines,
    }

@router.post("/{server_id}/setup/retry")
def retry_setup(server_id, background_tasks, db, _):
    server = server_service.get_server(db, server_id)
    server.setup_status = None
    server.setup_step   = None
    server.setup_error  = None
    server.setup_log    = None
    db.commit()
    background_tasks.add_task(run_server_setup, server_id)
    return {"success": True, "message": "Setup restarted"}

@router.get("/{server_id}/ssh-password")
def get_ssh_password(server_id, db, _):
    server = server_service.get_server(db, server_id)
    password = None
    if server.ssh_password_enc:
        try:
            password = decrypt_value(server.ssh_password_enc)
        except Exception:
            pass
    if not password and server.ssh_password:
        password = server.ssh_password
    if not password:
        raise HTTPException(status_code=404, detail="SSH password not found")
    return {"password": password}
```

---

## setup_service.py — полный код

### Шифрование

```python
def _get_fernet() -> Fernet:
    from app.core.config import settings
    key = getattr(settings, "SECRET_KEY", None)
    import base64, hashlib
    digest = hashlib.sha256(key.encode()).digest()
    b64 = base64.urlsafe_b64encode(digest)
    return Fernet(b64)

def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()

def decrypt_value(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()
```

### SSH-хелперы

```python
def _connect(ip, port, user, password=None, private_key_pem=None, timeout=15):
    """Подключение к серверу через paramiko."""
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


def _exec(client, cmd, timeout=120):
    """
    Выполняет команду по SSH с жёстким таймаутом через select().
    recv_exit_status() блокируется вечно при зависании процесса —
    поэтому читаем через select с дедлайном.
    Возвращает: (exit_code, stdout, stderr)
    """
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        return -1, "", "SSH transport не активен"
    chan = transport.open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out_chunks, err_chunks = [], []
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            chan.close()
            return -1, "".join(out_chunks), "".join(err_chunks) + f"\n[TIMEOUT after {timeout}s]"
        r, _, _ = select.select([chan], [], [], min(remaining, 2.0))
        if chan in r:
            if chan.recv_ready():
                data = chan.recv(65536)
                if data: out_chunks.append(data.decode("utf-8", errors="replace"))
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if data: err_chunks.append(data.decode("utf-8", errors="replace"))
        if chan.exit_status_ready():
            while chan.recv_ready():
                data = chan.recv(65536)
                if data: out_chunks.append(data.decode("utf-8", errors="replace"))
            while chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if data: err_chunks.append(data.decode("utf-8", errors="replace"))
            code = chan.recv_exit_status()
            chan.close()
            return code, "".join(out_chunks), "".join(err_chunks)


def _s(cmd, use_sudo):
    """Префиксует команду через 'sudo -n' если пользователь не root."""
    if not use_sudo:
        return cmd
    cmd = cmd.strip()
    if cmd.startswith("sudo ") or cmd.startswith("nohup ") or cmd.startswith("echo "):
        return cmd
    return "sudo -n " + cmd

def _se(client, cmd, use_sudo, timeout=120):
    """_exec + автоматический sudo."""
    return _exec(client, _s(cmd, use_sudo), timeout=timeout)
```

### Вспомогательные генераторы

```python
def _gen_password(length=24):
    """Генерирует случайный пароль с буквами, цифрами и спецсимволами."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd

def _gen_ssh_port():
    """Случайный порт 10000–65000."""
    return random.randint(10000, 65000)

def _gen_username():
    return f"vpnadmin{random.randint(1000, 9999)}"

def _gen_ed25519_keypair():
    """
    Генерирует пару Ed25519.
    Возвращает (private_pem, public_openssh).
    Использует cryptography напрямую (совместимо с paramiko 3.x).
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption
    )
    import base64, struct
    raw_key = Ed25519PrivateKey.generate()
    priv_pem = raw_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode()
    pub_raw = raw_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    algo = b"ssh-ed25519"
    wire = struct.pack(">I", len(algo)) + algo + struct.pack(">I", len(pub_raw)) + pub_raw
    pub_b64 = base64.b64encode(wire).decode()
    pub_openssh = f"ssh-ed25519 {pub_b64} vpnadmin"
    return priv_pem, pub_openssh
```

### Точка входа и инициализация

```python
def run_server_setup(server_id: int):
    """Точка входа — запускается как background task."""
    db = SessionLocal()
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            return
        _run(db, server)
    except Exception as e:
        logger.error(f"Setup crashed for server {server_id}: {e}", exc_info=True)
    finally:
        db.close()


def _run(db, server):
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
    use_sudo = (cur_user != "root")   # True если подключаемся не как root
```

---

## Шаг 1 — Проверка подключения

```python
_update_setup(db, server, step="step1", log_line="[1] Проверка подключения...")
client = _connect(cur_ip, cur_port, cur_user, password=cur_pass, private_key_pem=cur_key)
code, out, _ = _exec(client,
    "echo OK && id && "
    "lsb_release -d 2>/dev/null || true && "
    "uptime -p 2>/dev/null || uptime && "
    "df -h / | tail -1 && "
    "free -h | grep Mem")
client.close()
if "OK" not in out:
    raise RuntimeError("Сервер не ответил на echo OK")
# Логируем строки ответа (ОС, аптайм, диск, память)
```

---

## Шаг 2 — Установка стека

### 2.0 Очистка apt-lock + apt update
```python
_clear_apt_locks(client, db, server, use_sudo)
# _clear_apt_locks:
#   1. systemctl stop unattended-upgrades && pkill -9 -f unattended-upgrades/apt-get
#   2. Ждёт до 120 сек пока процессы завершатся
#   3. Принудительно удаляет lock-файлы если не освободились:
#      rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock
#      dpkg --configure -a

_se(client, "DEBIAN_FRONTEND=noninteractive apt-get update -qq", use_sudo, timeout=120)
```

### 2.1 Базовые зависимости
```python
_se(client,
    "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
    "curl wget unzip git ca-certificates gnupg lsb-release", use_sudo, timeout=180)
```

### 2.2 Xray-core (EU и RU)
```python
# Сначала официальный скрипт, fallback — прямое скачивание бинарника с GitHub
XRAY_SCRIPT = """
bash <(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install
# При неудаче — определяем архитектуру, качаем zip, распаковываем в /usr/local/bin/xray
# Создаём systemd unit /etc/systemd/system/xray.service
# Минимальный /usr/local/etc/xray/config.json
# systemctl daemon-reload && enable && restart
"""
_exec(client, f"{'sudo -n ' if use_sudo else ''}bash -s << '__XRAY__'\n{XRAY_SCRIPT}\n__XRAY__", timeout=300)

# После установки:
server.xray_installed = True
# Генерируем Reality-ключи:
_, keys_out, _ = _exec(client, "xray x25519 2>/dev/null || true", timeout=15)
# Парсим "Public key: ..." -> server.xray_public_key
```

### 2.3 AmneziaWG (EU и RU)
```python
AWG_SCRIPT = """
apt-get install -y -qq software-properties-common
add-apt-repository -y ppa:amnezia/ppa
apt-get update -qq
apt-get install -y -qq amneziawg amneziawg-tools
modprobe amneziawg 2>/dev/null || true
"""
# После установки: генерируем серверные ключи
# awg genkey | tee /tmp/awg_server.key | awg pubkey -> server.awg_server_public_key
server.awg_installed = True
```

### 2.4 NaiveProxy (EU и RU)
```python
# Бинарник напрямую с GitHub releases (не через Caddy)
NAIVE_SCRIPT = """
ARCH=$(dpkg --print-architecture)  # amd64 -> linux-x64, arm64 -> linux-arm64
NAIVE_VERSION=$(curl api.github.com/repos/klzgrad/naiveproxy/releases/latest)
curl -fsSL naiveproxy-${VERSION}-${ARCH}.tar.xz | tar -xf
cp naive /usr/local/bin/naive && chmod +x
mkdir -p /etc/naiveproxy
"""
server.naiveproxy_installed = True
server.caddy_version = naive_version  # поле переиспользуется для версии NaiveProxy
```

### 2.5 WARP — только для RU серверов
```python
if not is_eu:
    from app.services.deploy_service import install_warp
    ok, msg = install_warp(server)
    # install_warp из deploy_service.py:
    # WARP_INSTALL_SCRIPT:
    #   apt-get install -y curl
    #   curl https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -> trusted.gpg.d
    #   echo deb https://pkg.cloudflareclient.com/ -> /etc/apt/sources.list.d/cloudflare-client.list
    #   apt-get update && apt-get install -y cloudflare-warp
    #   warp-cli register && warp-cli connect
    #   systemctl enable --now warp-svc
    server.warp_installed = True
```

---

## Шаг 3 — Настройка безопасности

```
use_sudo = True если cur_user != "root"
Все команды идут через _se(client, cmd, use_sudo)
```

### 3.1 apt upgrade критичных пакетов
```python
# Сначала убиваем unattended-upgrades и очищаем lock
_se(client, "systemctl stop unattended-upgrades && pkill -9 -f apt-get && "
    "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock && dpkg --configure -a", use_sudo)
_se(client,
    "DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y -qq "
    "-o DPkg::Lock::Timeout=60 openssh-server openssl 2>/dev/null || true", use_sudo, timeout=120)
```

### 3.2 Установка Fail2Ban и UFW
```python
_se(client, "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban ufw",
    use_sudo, timeout=180)
# При неудаче: очищаем lock и повторяем
```

### 3.3 Запуск и настройка Fail2Ban
```python
# Отдельные команды — чтобы systemd-шум не попадал в err
_se(client, "systemctl enable fail2ban 2>/dev/null || true", use_sudo, timeout=15)
_se(client, "systemctl start fail2ban 2>/dev/null || true", use_sudo, timeout=15)
_se(client, """printf '[DEFAULT]\\nbantime=3600\\nfindtime=600\\nmaxretry=5\\n\\n[sshd]\\nenabled=true\\n'
    > /etc/fail2ban/jail.local""", use_sudo, timeout=10)
_se(client, "systemctl restart fail2ban 2>/dev/null || true", use_sudo, timeout=15)
# Проверка: systemctl is-active fail2ban
```

### 3.4 Настройка UFW
```python
_se(client, "ufw --force reset", use_sudo)
_se(client, "ufw default deny incoming && ufw default allow outgoing", use_sudo)
_se(client, f"ufw allow {cur_port}/tcp", use_sudo)  # текущий SSH порт
_se(client, "ufw allow 22/tcp", use_sudo)            # оставляем 22 до смены
_se(client, "ufw allow 80/tcp && ufw allow 443/tcp", use_sudo)
_se(client, "ufw allow 51820/udp && ufw allow 51821/udp", use_sudo)  # AWG
if not is_eu:
    _se(client, "ufw allow 2408/udp", use_sudo)      # WARP (только RU)
_se(client, "ufw --force enable", use_sudo)
# Проверка: ufw status | head -1 → "Status: active"
```

### 3.5 Новый SSH пользователь
```python
# EU серверы: создаём нового изолированного пользователя vpnadmin{XXXX}
# RU серверы: пропускаем, работаем с текущим пользователем (fakeart и т.п.)
if is_eu:
    new_user = _gen_username()   # vpnadmin1234
    _se(client, f"id {new_user} &>/dev/null || useradd -m -s /bin/bash {new_user}", use_sudo)
    _se(client, f"usermod -aG sudo {new_user}", use_sudo)
    _se(client, f"echo '{new_user} ALL=(ALL) NOPASSWD:ALL' | tee /etc/sudoers.d/{new_user}", use_sudo)
    _se(client, f"mkdir -p /home/{new_user}/.ssh && chmod 700 /home/{new_user}/.ssh", use_sudo)
    _se(client, f"cp ~/.ssh/authorized_keys /home/{new_user}/.ssh/authorized_keys", use_sudo)
    _se(client, f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh", use_sudo)
else:
    # RU: лог "[3.5] ℹ️ RU-сервер: используем текущего пользователя {cur_user}"
    new_user = cur_user
```

### 3.6 Генерация SSH-ключа Ed25519
```python
new_priv, new_pub = _gen_ed25519_keypair()
_exec(client,
    f"mkdir -p /home/{new_user}/.ssh && "
    f"echo '{new_pub}' >> /home/{new_user}/.ssh/authorized_keys && "
    f"chown -R {new_user}:{new_user} /home/{new_user}/.ssh && "
    f"chmod 600 /home/{new_user}/.ssh/authorized_keys")
# Проверка подключения по новому ключу
test_cli = _connect(cur_ip, cur_port, new_user, private_key_pem=new_priv)
_exec(test_cli, "echo KEY_OK")
cur_user = new_user
cur_key  = new_priv
cur_pass = None
sec_ssh_key_set = True
```

### 3.7 Смена пароля
```python
new_password = _gen_password()
_exec(client, f"echo '{new_user}:{new_password}' | {'sudo -n ' if use_sudo else ''}chpasswd")
```

### 3.8 Отключение парольной аутентификации
```python
# Патчим /etc/ssh/sshd_config и все /etc/ssh/sshd_config.d/*.conf
_se(client,
    "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && "
    "for f in /etc/ssh/sshd_config.d/*.conf 2>/dev/null; do "
    "  sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' $f; "
    "done && systemctl reload sshd 2>/dev/null || service ssh reload", use_sudo)
sec_password_auth_disabled = True
```

### 3.9 Смена SSH-порта
```python
new_port = _gen_ssh_port()   # 10000–65000
# 1. Открываем новый порт в UFW
_se(client, f"ufw allow {new_port}/tcp", use_sudo)
# 2. Прописываем в sshd_config
_se(client, f"sed -i 's/^#*Port .*/Port {new_port}/' /etc/ssh/sshd_config", use_sudo)
# 3. Отключаем socket-активацию (иначе systemd переопределит порт)
_se(client, "systemctl disable --now ssh.socket 2>/dev/null || true", use_sudo)
# 4. Рестарт через nohup (чтобы не потерять соединение)
_exec(client, "nohup sh -c 'sleep 2 && systemctl restart ssh' &>/dev/null &")
time.sleep(5)
# 5. Проверяем новый порт (fallback на 22 при неудаче)
try:
    test = _connect(cur_ip, new_port, cur_user, private_key_pem=cur_key)
    _exec(test, "echo PORT_OK"); test.close()
    _se(client, f"ufw delete allow {cur_port}/tcp 2>/dev/null || true", use_sudo)  # закрываем старый
    cur_port = new_port
    server.ssh_port_actual = new_port
except Exception:
    cur_port = 22   # откат на 22
    server.ssh_port_actual = 22
# 6. Сохраняем итоговые credentials
server.ssh_user_actual = cur_user
server.ssh_port        = cur_port
server.ssh_password    = None
server.ssh_password_enc = encrypt_value(new_password)
server.ssh_key          = None
server.ssh_private_key_enc = encrypt_value(cur_key)
```

---

## Шаг 4 — Сбор информации о сервере

```python
# Переподключаемся с новыми credentials
client = _connect(cur_ip, cur_port, cur_user, private_key_pem=cur_key)

# Страна по IP
_, country_out, _ = _exec(client,
    "curl -sf 'http://ip-api.com/json/?fields=country,countryCode' 2>/dev/null || echo '{}'")
# -> server.country, server.country_code

# Версии компонентов
_exec(client, "xray version 2>/dev/null | head -1")   # -> server.xray_version
_exec(client, "/usr/local/bin/naive --version 2>/dev/null | head -1")  # -> server.caddy_version
_exec(client, "warp-cli --version 2>/dev/null | head -1")  # -> server.warp_version (только RU)

# Системная информация
_exec(client, "nproc && cat /proc/cpuinfo | grep 'model name' | head -1")  # CPU
_exec(client, "free -b | grep Mem")                    # RAM
_exec(client, "df -b / | tail -1")                     # Диск
_exec(client, "uptime -s 2>/dev/null || uptime")       # Аптайм

# Security flags записываем в БД
server.sec_fail2ban       = sec_fail2ban_active
server.sec_ufw            = sec_ufw_active
server.sec_password_login = not sec_password_auth_disabled
```

---

## Шаг 5 — Финальная проверка сервисов

```python
# Список проверок: (имя, install_cmd, run_cmd, is_critical)
checks = [
    ("SSH",    "echo alive",                               "echo alive",          True),
    ("Xray",   "which xray || systemctl is-active xray",  "systemctl is-active xray", True),
    ("AmneziaWG", "which awg || dpkg -l amneziawg ...",   None,                  True),
    ("NaiveProxy","which naive",                           "naive --version",     True),
    ("Fail2Ban",  "which fail2ban-client",                 "systemctl is-active fail2ban", False),
    ("UFW",       "which ufw",                             "sudo ufw status | head -1",    False),
]
# Для RU добавляется:
if not is_eu:
    checks.append(("WARP",
        "which warp-cli || dpkg -l cloudflare-warp ...",
        "warp-cli status 2>/dev/null || echo 'warp-status-failed'",
        False))

# Логика проверки WARP:
# Если warp-cli отвечает "Unable to connect..." — значит warp-svc не запущен
# Пробуем запустить:
if "unable" in out_lower or not out_r.strip():
    _exec(client, "sudo -n systemctl start warp-svc 2>/dev/null || true")
    time.sleep(3)
    _, out_r, _ = _exec(client, "warp-cli status 2>/dev/null || echo 'warp-status-failed'")
is_up = "connected" in out_lower or "status: connected" in out_lower

# Итоговый статус
if critical_ok:
    server.setup_status = "done"
    server.status = ServerStatus.ONLINE
else:
    server.setup_status = "failed"
    server.status = ServerStatus.NOT_CONFIGURED
```

---

## Разница EU vs RU

| Шаг | EU сервер | RU сервер |
|-----|-----------|-----------|
| 2.5 WARP | ❌ Не устанавливается | ✅ Устанавливается |
| 3.4 UFW порт 2408 | ❌ Нет | ✅ Открывается (WARP UDP) |
| 3.5 Новый пользователь | ✅ Создаётся vpnadmin{XXXX} | ℹ️ Пропускается, используем текущего |
| Step 5 WARP check | ❌ Нет | ✅ Проверяется с авто-запуском warp-svc |
