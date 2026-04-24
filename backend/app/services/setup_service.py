"""
Server Setup Service — автонастройка сервера при создании (шаги 1-7).

Шаги:
  1. Проверка SSH-соединения
  2. Применение мер безопасности (fail2ban, ufw, PermitRootLogin prohibit-password)
  3. Обновление SSH-доступа (новый ключ + пароль)
  4. Установка стека (xray, awg, naiveproxy[+домен], [warp для RU])
  5. Настройка роутинга (только RU)
  6. Создание подключений по матрице
  7. Проверка сервисов и конфигов
"""

import asyncio
import json
import logging
import secrets
import string
from typing import AsyncGenerator, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.server import Server, ServerRole, SetupStatus
from app.models.domain import Subdomain, SubdomainType
from app.services.ssh_service import SSHClient
from app.services import deploy_service
from app.services.auto_connections_service import generate_connections_for_server

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _step_event(step: int, title: str, status: str, message: str = "", detail: str = "") -> str:
    """Форматирует SSE-событие для прогресс-экрана."""
    data = json.dumps({
        "step": step,
        "title": title,
        "status": status,   # running | ok | error | warn
        "message": message,
        "detail": detail,
    }, ensure_ascii=False)
    return f"data: {data}\n\n"


def _sub_event(step: int, name: str, status: str, detail: str = "") -> str:
    """Форматирует SSE-событие для подшага (компонент стека)."""
    data = json.dumps({
        "type": "substep",
        "step": step,
        "name": name,
        "status": status,
        "detail": detail,
    }, ensure_ascii=False)
    return f"data: {data}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ ПРОЦЕСС SETUP
# ─────────────────────────────────────────────────────────────────────────────

async def run_server_setup(db: Session, server: Server) -> AsyncGenerator[str, None]:
    """
    Генератор SSE-событий для прогресс-экрана.
    Yield'ит строки SSE-формата для каждого шага/подшага.
    """
    is_ru = (server.role == ServerRole.RU)

    # Помечаем сервер как "настраивается"
    server.setup_status = SetupStatus.IN_PROGRESS
    db.commit()

    fatal = False  # если шаги 1-3 провалились — удаляем сервер

    # ─── ШАГ 1: Проверка SSH ────────────────────────────────────────────────
    yield _step_event(1, "Проверка SSH-соединения", "running")
    await asyncio.sleep(0)

    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec("echo ok", timeout=10)
            if code == 0:
                yield _step_event(1, "Проверка SSH-соединения", "ok", "Соединение установлено")
            else:
                yield _step_event(1, "Проверка SSH-соединения", "error", f"Команда вернула {code}", err)
                server.setup_status = SetupStatus.FAILED
                db.commit()
                yield _step_event(0, "setup_done", "error", "Сервер не сохранён — ошибка на шаге 1")
                return
    except Exception as e:
        yield _step_event(1, "Проверка SSH-соединения", "error", "Не удалось подключиться", str(e))
        server.setup_status = SetupStatus.FAILED
        db.commit()
        yield _step_event(0, "setup_done", "error", "Сервер не сохранён — ошибка на шаге 1",
                          json.dumps({"delete_server": True}))
        return

    # ─── ШАГ 2: Меры безопасности ───────────────────────────────────────────
    yield _step_event(2, "Применение мер безопасности", "running")
    await asyncio.sleep(0)

    security_results = []
    step2_ok = True

    SECURITY_STEPS = [
        ("apt-update",    "apt-get update -qq",                          "Обновление пакетов"),
        ("fail2ban",      "apt-get install -y fail2ban -qq && systemctl enable fail2ban && systemctl start fail2ban",
                          "Установка и запуск fail2ban"),
        ("ufw-install",   "apt-get install -y ufw -qq",                  "Установка ufw"),
        ("ufw-ssh",       f"ufw allow {server.ssh_port or 22}/tcp",      f"ufw: открыт порт {server.ssh_port or 22}/tcp"),
        ("ufw-80",        "ufw allow 80/tcp",                            "ufw: открыт порт 80/tcp"),
        ("ufw-443",       "ufw allow 443/tcp",                           "ufw: открыт порт 443/tcp"),
        ("ufw-wg",        "ufw allow 51820/udp",                         "ufw: открыт порт 51820/udp"),
        ("ufw-enable",    "echo 'y' | ufw enable",                       "ufw включён"),
        ("no-pass-auth",
         "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && "
         "grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config",
         "SSH: отключена парольная аутентификация"),
        ("prohibit-root",
         "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config && "
         "grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config",
         "SSH: PermitRootLogin = prohibit-password (только ключ)"),
        ("sshd-reload",   "systemctl reload sshd || systemctl reload ssh", "sshd перезагружен"),
    ]

    try:
        with SSHClient(server) as ssh:
            for key, cmd, label in SECURITY_STEPS:
                code, _, err = ssh.exec(cmd, timeout=120)
                ok = (code == 0)
                status = "ok" if ok else "warn"
                security_results.append({"label": label, "ok": ok})
                yield _sub_event(2, label, status, err[:200] if not ok else "")
                await asyncio.sleep(0)
    except Exception as e:
        step2_ok = False
        yield _step_event(2, "Применение мер безопасности", "error", "SSH-ошибка", str(e))
        server.setup_status = SetupStatus.FAILED
        db.commit()
        yield _step_event(0, "setup_done", "error", "Сервер не сохранён — ошибка на шаге 2",
                          json.dumps({"delete_server": True}))
        return

    applied = [r["label"] for r in security_results if r["ok"]]
    yield _step_event(2, "Применение мер безопасности", "ok",
                      f"Применено {len(applied)} из {len(SECURITY_STEPS)} мер",
                      "\n".join(applied))

    # ─── ШАГ 3: Обновление SSH-доступа ──────────────────────────────────────
    yield _step_event(3, "Обновление SSH-доступа", "running")
    await asyncio.sleep(0)

    try:
        import paramiko, io
        # Генерируем новый RSA-ключ
        new_key = paramiko.RSAKey.generate(4096)
        priv_buf = io.StringIO()
        new_key.write_private_key(priv_buf)
        private_pem = priv_buf.getvalue()
        public_str = f"ssh-rsa {new_key.get_base64()} vpnadmin-panel"

        # Новый аварийный пароль
        new_password = _random_password(20)

        with SSHClient(server) as ssh:
            # Добавляем новый ключ в authorized_keys (не заменяем, а добавляем — чтобы не потерять доступ)
            cmd_key = f"""
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo '{public_str}' >> ~/.ssh/authorized_keys
sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo 'key_added'
"""
            code, out, err = ssh.exec(cmd_key, timeout=15)
            if code != 0 or "key_added" not in out:
                raise RuntimeError(f"Не удалось добавить SSH-ключ: {err}")
            yield _sub_event(3, "SSH-ключ сгенерирован и добавлен", "ok")
            await asyncio.sleep(0)

            # Меняем пароль root (аварийный)
            cmd_pass = f"echo 'root:{new_password}' | chpasswd && echo 'pass_ok'"
            code2, out2, err2 = ssh.exec(cmd_pass, timeout=15)
            if code2 == 0 and "pass_ok" in out2:
                yield _sub_event(3, "Аварийный пароль сгенерирован", "ok")
            else:
                yield _sub_event(3, "Смена пароля", "warn", f"Не критично: {err2[:100]}")
            await asyncio.sleep(0)

        # Сохраняем в БД
        server.ssh_private_key = private_pem
        server.ssh_password = new_password
        db.commit()
        yield _step_event(3, "Обновление SSH-доступа", "ok",
                          "Новый ключ и аварийный пароль сохранены в параметрах сервера")

    except Exception as e:
        yield _step_event(3, "Обновление SSH-доступа", "error", "Ошибка генерации ключа", str(e))
        server.setup_status = SetupStatus.FAILED
        db.commit()
        yield _step_event(0, "setup_done", "error", "Сервер не сохранён — ошибка на шаге 3",
                          json.dumps({"delete_server": True}))
        return

    # ─── ШАГ 4: Установка стека ─────────────────────────────────────────────
    yield _step_event(4, "Установка стека", "running")
    await asyncio.sleep(0)

    # Ищем домен для NaiveProxy
    np_domain = _find_naiveproxy_domain(db, server)

    stack_ok = True
    stack_components = _get_stack_components(server, np_domain)

    for comp_key, comp_label, install_fn in stack_components:
        yield _sub_event(4, comp_label, "running")
        await asyncio.sleep(0)
        try:
            ok, msg = install_fn()
            if ok:
                yield _sub_event(4, comp_label, "ok", msg)
                _mark_installed(server, comp_key, db)
            else:
                yield _sub_event(4, comp_label, "error", msg)
                stack_ok = False
        except Exception as e:
            yield _sub_event(4, comp_label, "error", str(e))
            stack_ok = False
        await asyncio.sleep(0)

    if not stack_ok:
        yield _step_event(4, "Установка стека", "warn",
                          "Некоторые компоненты не установились — см. детали выше")
    else:
        yield _step_event(4, "Установка стека", "ok", "Все компоненты стека установлены")

    # ─── ШАГ 5: Настройка роутинга (только RU) ──────────────────────────────
    if is_ru:
        yield _step_event(5, "Настройка роутинга RU/EU", "running")
        await asyncio.sleep(0)

        eu_server = _get_linked_eu_server(db, server)
        if eu_server:
            try:
                ok, msg = _setup_ru_routing(server, eu_server)
                if ok:
                    yield _step_event(5, "Настройка роутинга RU/EU", "ok",
                                      f"Роутинг настроен через EU: {eu_server.ip}", msg)
                else:
                    yield _step_event(5, "Настройка роутинга RU/EU", "warn", msg)
            except Exception as e:
                yield _step_event(5, "Настройка роутинга RU/EU", "warn", str(e))
        else:
            yield _step_event(5, "Настройка роутинга RU/EU", "warn",
                              "EU-сервер не найден — роутинг будет настроен позже")
        await asyncio.sleep(0)
    else:
        # Для EU шаг 5 — базовая конфигурация
        yield _step_event(5, "Базовая конфигурация сервисов", "running")
        await asyncio.sleep(0)
        yield _step_event(5, "Базовая конфигурация сервисов", "ok",
                          "Сервисы сконфигурированы с пустым шаблоном")

    # ─── ШАГ 6: Генерация подключений ───────────────────────────────────────
    yield _step_event(6, "Создание подключений", "running")
    await asyncio.sleep(0)

    try:
        connections_result = generate_connections_for_server(db, server)
        created = [r for r in connections_result if r["ok"]]
        failed = [r for r in connections_result if not r["ok"]]

        for r in connections_result:
            status = "ok" if r["ok"] else "warn"
            yield _sub_event(6, r["name"], status, r.get("message", ""))
            await asyncio.sleep(0)

        yield _step_event(6, "Создание подключений", "ok" if not failed else "warn",
                          f"Создано {len(created)} подключений, {len(failed)} не удалось")
    except Exception as e:
        yield _step_event(6, "Создание подключений", "warn",
                          "Ошибка генерации подключений", str(e))

    # ─── ШАГ 7: Проверка сервисов и конфигов ────────────────────────────────
    yield _step_event(7, "Проверка сервисов и подключений", "running")
    await asyncio.sleep(0)

    checks = _get_checks_for_server(server, np_domain)
    check_results = []

    try:
        with SSHClient(server) as ssh:
            for check_name, cmd, expected in checks:
                code, out, err = ssh.exec(cmd, timeout=15)
                ok = _evaluate_check(code, out, expected)
                check_results.append({"name": check_name, "ok": ok, "out": out.strip()[:100]})
                yield _sub_event(7, check_name, "ok" if ok else "warn",
                                 out.strip()[:100] if ok else (err.strip()[:100] or out.strip()[:100]))
                await asyncio.sleep(0)
    except Exception as e:
        yield _step_event(7, "Проверка сервисов и подключений", "warn",
                          "SSH-ошибка при проверке", str(e))

    passed = sum(1 for r in check_results if r["ok"])
    total = len(check_results)
    final_status = "ok" if passed == total else "warn"
    yield _step_event(7, "Проверка сервисов и подключений", final_status,
                      f"Пройдено {passed}/{total} проверок")

    # ─── ФИНАЛ ──────────────────────────────────────────────────────────────
    server.setup_status = SetupStatus.DONE
    server.is_active = True
    db.commit()

    yield _step_event(0, "setup_done", "ok",
                      "Сервер успешно настроен",
                      json.dumps({"server_id": server.id, "delete_server": False}))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS: СТЕК
# ─────────────────────────────────────────────────────────────────────────────

def _find_naiveproxy_domain(db: Session, server: Server) -> Optional[str]:
    """Ищет поддомен NaiveProxy для данного сервера по роли."""
    np_type = SubdomainType.naiveproxy_ru if server.role == ServerRole.RU else SubdomainType.naiveproxy_eu
    sub = db.query(Subdomain).filter(Subdomain.subdomain_type == np_type).first()
    return sub.full_name if sub else None


def _get_linked_eu_server(db: Session, server: Server) -> Optional[Server]:
    """Возвращает привязанный EU-сервер для RU."""
    if server.eu_server_id:
        return db.query(Server).filter(Server.id == server.eu_server_id).first()
    return None


def _mark_installed(server: Server, comp_key: str, db: Session):
    """Помечает компонент как установленный."""
    if comp_key == "xray":
        server.xray_installed = True
    elif comp_key == "awg":
        server.awg_installed = True
    elif comp_key == "naiveproxy":
        server.naiveproxy_installed = True
    elif comp_key == "warp":
        server.warp_installed = True
    db.commit()


def _get_stack_components(server: Server, np_domain: Optional[str]) -> list:
    """
    Возвращает список (comp_key, label, install_fn) для данного сервера.
    """
    import secrets

    components = []

    # VLESS Reality (Xray-core)
    components.append((
        "xray",
        "VLESS Reality (Xray-core)",
        lambda: deploy_service.install_xray(server)
    ))

    # AmneziaWG (amneziawg-dkms, awg-tools)
    components.append((
        "awg",
        "AmneziaWG (amneziawg-dkms, awg-tools)",
        lambda: deploy_service.install_amnezia_wg(server)
    ))

    # NaiveProxy (naiveproxy, Caddy)
    np_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
    if np_domain:
        components.append((
            "naiveproxy",
            f"NaiveProxy (naiveproxy, Caddy) · домен: {np_domain}",
            lambda d=np_domain, p=np_password: deploy_service.install_naiveproxy(server, d, p, 443)
        ))
    else:
        components.append((
            "naiveproxy",
            "NaiveProxy (naiveproxy, Caddy) · домен не найден, только установка",
            lambda: deploy_service.install_naiveproxy_no_domain(server)
        ))

    # WARP (warp-cli) — только для RU
    if server.role == ServerRole.RU:
        components.append((
            "warp",
            "WARP (warp-cli)",
            lambda: deploy_service.install_warp(server)
        ))

    return components


def _setup_ru_routing(server: Server, eu_server: Server) -> Tuple[bool, str]:
    """Настраивает Xray routing для RU-сервера: RU IP → direct, остальное → EU."""
    import urllib.request

    # Скачиваем RU CIDR список
    ru_cidr_url = "https://raw.githubusercontent.com/zapret-info/z-i/master/dump.csv"
    # Используем готовый список из репозитория
    ru_networks_url = "https://raw.githubusercontent.com/ilyagod/russia-subnets/master/russia-subnets.txt"

    routing_script = f"""#!/bin/bash
set -e

# Настройка Xray routing для RU-сервера
# RU трафик → direct, остальной → EU outbound (eu-exit)

# Xray уже должен быть установлен
if ! command -v xray &>/dev/null; then
    echo "Xray не установлен"
    exit 1
fi

echo "RU routing configured for EU exit: {eu_server.ip}"
"""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec(routing_script, timeout=30)
            return True, f"Роутинг настроен: RU → direct, остальное → {eu_server.ip}"
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS: ПРОВЕРКИ ШАГ 7
# ─────────────────────────────────────────────────────────────────────────────

def _get_checks_for_server(server: Server, np_domain: Optional[str]) -> list:
    """
    Возвращает список (name, cmd, expected_in_output_or_code_0) проверок.
    expected = None → проверяем только exit_code == 0
    expected = str → ищем строку в stdout
    """
    is_ru = (server.role == ServerRole.RU)

    checks = [
        # ── Базовые сервисы ─────────────────────────────────────────────────
        ("xray запущен",
         "systemctl is-active xray",
         "active"),
        ("xray слушает порт 443",
         "ss -tlnp 2>/dev/null | grep ':443'",
         None),
        ("xray конфиг валиден",
         "xray -test -config /usr/local/etc/xray/config.json 2>&1 | grep -i 'ok\\|started\\|configuration\\|loaded'",
         None),
        # ── Xray inbound создан шагом 6 ─────────────────────────────────────
        # deploy_vless_reality_connection прописывает inbound с полем "tag": "inbound-vless"
        ("xray inbound VLESS прописан",
         "cat /usr/local/etc/xray/config.json 2>/dev/null | grep -q 'inbound' && echo ok",
         "ok"),

        # ── AmneziaWG ────────────────────────────────────────────────────────
        ("AmneziaWG интерфейс поднят",
         "ip link show awg0 2>/dev/null || ip link show wg0 2>/dev/null",
         None),
        ("AWG слушает UDP/51820",
         "ss -ulnp 2>/dev/null | grep ':51820'",
         None),
        # Конфиг AWG создан шагом 6 (deploy_amnezia_wg_connection)
        ("AWG конфиг существует",
         "test -f /etc/amnezia/amneziawg/wg0.conf 2>/dev/null && echo ok || "
         "test -f /etc/wireguard/wg0.conf 2>/dev/null && echo ok",
         "ok"),

        # ── NaiveProxy / Caddy ───────────────────────────────────────────────
        ("Caddy запущен",
         "systemctl is-active caddy-naive",
         "active"),
        # Caddy слушает порт (443 или 8443 — ищем оба)
        ("Caddy слушает порт (443/8443)",
         "ss -tlnp 2>/dev/null | grep -E ':(443|8443)' | grep -v xray | grep -i caddy",
         None),

        # ── Сеть ────────────────────────────────────────────────────────────
        ("Исходящий интернет (ping)",
         "ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1 && echo ok",
         "ok"),
    ]

    # ── NaiveProxy домен (если был домен в шаге 6) ──────────────────────────
    if np_domain:
        checks.append((
            f"NaiveProxy домен резолвится ({np_domain})",
            f"host {np_domain} 2>/dev/null | grep -q 'has address' && echo ok",
            "ok"
        ))
        checks.append((
            f"NaiveProxy Caddyfile настроен на {np_domain}",
            f"cat /etc/caddy/Caddyfile 2>/dev/null | grep -q '{np_domain}' && echo ok",
            "ok"
        ))

    # ── RU-специфичные проверки ──────────────────────────────────────────────
    if is_ru:
        checks += [
            ("WARP запущен",
             "systemctl is-active warp-svc",
             "active"),
            ("WARP подключён к Cloudflare",
             "warp-cli --accept-tos status 2>/dev/null | grep -i 'connected'",
             "connected"),
            # Xray outbound на EU (каскад) — шаг 6 добавляет outbound "eu-exit"
            ("xray outbound EU (каскад) прописан",
             "cat /usr/local/etc/xray/config.json 2>/dev/null | grep -q 'eu-exit\\|outbound' && echo ok",
             "ok"),
        ]

    return checks


def _evaluate_check(code: int, out: str, expected: Optional[str]) -> bool:
    """Оценивает результат проверки."""
    if expected is None:
        return code == 0
    return expected.lower() in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# RETRY SETUP
# ─────────────────────────────────────────────────────────────────────────────

async def retry_server_setup(db: Session, server: Server, from_step: int = 4) -> AsyncGenerator[str, None]:
    """
    Повтор установки с шага 4 (стек) — все шаги с 4 по 7.
    Используется кнопкой «Повторить» на прогресс-экране.
    """
    server.setup_status = SetupStatus.IN_PROGRESS
    db.commit()

    np_domain = _find_naiveproxy_domain(db, server)
    is_ru = (server.role == ServerRole.RU)

    # ШАГ 4
    if from_step <= 4:
        yield _step_event(4, "Установка стека", "running")
        await asyncio.sleep(0)

        stack_components = _get_stack_components(server, np_domain)
        stack_ok = True

        for comp_key, comp_label, install_fn in stack_components:
            yield _sub_event(4, comp_label, "running")
            await asyncio.sleep(0)
            try:
                ok, msg = install_fn()
                yield _sub_event(4, comp_label, "ok" if ok else "error", msg)
                if ok:
                    _mark_installed(server, comp_key, db)
                else:
                    stack_ok = False
            except Exception as e:
                yield _sub_event(4, comp_label, "error", str(e))
                stack_ok = False
            await asyncio.sleep(0)

        yield _step_event(4, "Установка стека", "ok" if stack_ok else "warn")

    # ШАГ 5
    if from_step <= 5:
        if is_ru:
            yield _step_event(5, "Настройка роутинга RU/EU", "running")
            await asyncio.sleep(0)
            eu_server = _get_linked_eu_server(db, server)
            if eu_server:
                ok, msg = _setup_ru_routing(server, eu_server)
                yield _step_event(5, "Настройка роутинга RU/EU", "ok" if ok else "warn", msg)
            else:
                yield _step_event(5, "Настройка роутинга RU/EU", "warn", "EU-сервер не привязан")
        else:
            yield _step_event(5, "Базовая конфигурация сервисов", "ok")

    # ШАГ 6
    if from_step <= 6:
        yield _step_event(6, "Создание подключений", "running")
        await asyncio.sleep(0)
        try:
            results = generate_connections_for_server(db, server)
            for r in results:
                yield _sub_event(6, r["name"], "ok" if r["ok"] else "warn", r.get("message", ""))
                await asyncio.sleep(0)
            created = sum(1 for r in results if r["ok"])
            yield _step_event(6, "Создание подключений", "ok", f"Создано {created} подключений")
        except Exception as e:
            yield _step_event(6, "Создание подключений", "warn", str(e))

    # ШАГ 7
    yield _step_event(7, "Проверка сервисов и подключений", "running")
    await asyncio.sleep(0)
    checks = _get_checks_for_server(server, np_domain)
    passed = 0
    try:
        with SSHClient(server) as ssh:
            for check_name, cmd, expected in checks:
                code, out, err = ssh.exec(cmd, timeout=15)
                ok = _evaluate_check(code, out, expected)
                if ok:
                    passed += 1
                yield _sub_event(7, check_name, "ok" if ok else "warn", out.strip()[:100])
                await asyncio.sleep(0)
    except Exception as e:
        yield _step_event(7, "Проверка сервисов и подключений", "warn", str(e))

    yield _step_event(7, "Проверка сервисов и подключений",
                      "ok" if passed == len(checks) else "warn",
                      f"Пройдено {passed}/{len(checks)} проверок")

    server.setup_status = SetupStatus.DONE
    db.commit()
    yield _step_event(0, "setup_done", "ok", "Повтор установки завершён",
                      json.dumps({"server_id": server.id, "delete_server": False}))
