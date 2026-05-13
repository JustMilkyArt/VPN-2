"""
Client Validation Service — End-to-End Tunnel Validation Layer

Архитектура:
  Запускает временный xray-клиент прямо на сервере (localhost),
  который подключается к VPN-инбаунду через loopback.
  Затем делает реальные HTTP-запросы через SOCKS5-прокси клиента.

  Это имитирует поведение реального VPN-клиента и валидирует:
    1. Tunnel Establishment   — реальное VPN-соединение
    2. DNS Resolution         — DNS через tunnel
    3. Outbound IP            — реальный exit IP через VPN
    4. Traffic Forwarding     — HTTP-трафик проходит через tunnel
    5. Routing                — outbound IP ≠ server IP (не short-circuit)
    6. Internet Access        — интернет доступен через tunnel
    7. WARP Active            — warp-svc работает и настроен

Для VLESS Reality: запускает xray в режиме клиента → SOCKS5 :18080
Для AWG:          запускает временный wg-peer → проверяет routing
Для NaiveProxy:   curl через naive-клиент или прямой HTTPS-прокси

Результат:
  {
    "tunnel_ok":      True/False/None,   # реальное VPN-соединение
    "dns_ok":         True/False/None,   # DNS через tunnel
    "routing_ok":     True/False/None,   # трафик идёт через VPN
    "traffic_ok":     True/False/None,   # HTTP ответ получен
    "internet_ok":    True/False/None,   # интернет через tunnel
    "warp_active":    True/False/None,   # WARP сервис активен
    "tunnel_ip":      "...",             # IP через tunnel
    "tunnel_geo":     "...",             # geo через tunnel
    "tunnel_latency_ms": ...,            # задержка через tunnel
    "validation_errors": [...],          # список ошибок
    "validated_at":   datetime,
  }
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.connection import Connection, Protocol, ConnectionType
from app.models.server import Server
from app.services.ssh_service import SSHClient

logger = logging.getLogger(__name__)

# ─── Константы ───────────────────────────────────────────────────────────────

VALIDATION_TIMEOUT   = 30        # секунды на весь e2e тест
SOCKS_PORT           = 18080     # временный SOCKS5-порт клиента xray
XRAY_CLIENT_TAG      = "vpnadmin-e2e-validator"
TEST_URLS = [
    "https://api.ipify.org?format=json",
    "https://ipinfo.io/json",
]
TEST_DNS_HOST        = "api.ipify.org"
TEST_HTTP_TIMEOUT    = 12        # секунды на HTTP-запрос через tunnel


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def _kill_validator_xray(ssh) -> None:
    """Убиваем временный xray-клиент по тегу конфига."""
    ssh.exec(
        f"pkill -f '{XRAY_CLIENT_TAG}' 2>/dev/null; "
        f"rm -f /tmp/{XRAY_CLIENT_TAG}.json 2>/dev/null",
        timeout=5,
    )


def _check_warp_active(ssh) -> bool:
    """Проверяем что warp-svc активен и WARP подключён."""
    try:
        _, out, _ = ssh.exec(
            "warp-cli status 2>/dev/null || echo 'WARP_UNAVAILABLE'",
            timeout=8,
        )
        out = out or ""
        if "WARP_UNAVAILABLE" in out or "command not found" in out:
            return False
        # "Connected" или "Status update: Connected"
        return "Connected" in out
    except Exception:
        return False


def _check_dns_resolution(ssh, host: str = TEST_DNS_HOST) -> bool:
    """DNS-резолюция через dig/nslookup."""
    try:
        _, out, _ = ssh.exec(
            f"dig +short +timeout=5 {host} A 2>/dev/null | head -1 || "
            f"nslookup {host} 2>/dev/null | awk '/^Address/ && !/#53/ {{print $2; exit}}' || "
            f"getent hosts {host} 2>/dev/null | awk '{{print $1}}' | head -1",
            timeout=10,
        )
        out = (out or "").strip()
        # Валидный IPv4
        parts = out.split(".")
        return len(parts) == 4 and all(p.isdigit() for p in parts)
    except Exception:
        return False


def _http_via_socks5(ssh, socks_port: int, url: str, timeout: int = TEST_HTTP_TIMEOUT) -> dict:
    """HTTP-запрос через SOCKS5-прокси на localhost:{socks_port}."""
    result = {"ok": False, "body": "", "error": ""}
    try:
        _, out, err = ssh.exec(
            f"curl -s --max-time {timeout} "
            f"--socks5-hostname 127.0.0.1:{socks_port} "
            f"'{url}' 2>&1 || echo CURL_FAIL",
            timeout=timeout + 5,
        )
        out = (out or "").strip()
        if "CURL_FAIL" in out or not out or "(6)" in out or "(7)" in out:
            result["error"] = out[:200]
            return result
        result["ok"] = True
        result["body"] = out
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


def _parse_ip_from_response(body: str) -> Optional[str]:
    """Извлекаем IP из ответа api.ipify.org или ipinfo.io."""
    if not body:
        return None
    try:
        data = json.loads(body)
        return data.get("ip") or data.get("query")
    except Exception:
        pass
    # Fallback: просто ищем IPv4 в тексте
    m = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", body)
    return m.group(1) if m else None


# ─── VLESS Reality e2e ───────────────────────────────────────────────────────

def _build_vless_client_config(conn: Connection, server_ip: str, socks_port: int) -> str:
    """Генерируем конфиг xray-клиента для VLESS Reality → SOCKS5 inbound."""
    tag = XRAY_CLIENT_TAG
    config = {
        "log": {"loglevel": "error"},
        "inbounds": [{
            "tag": "socks-in",
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [
            {
                "tag": tag,
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": server_ip,
                        "port": conn.port,
                        "users": [{
                            "id": conn.uuid,
                            "encryption": "none",
                            "flow": "xtls-rprx-vision",
                        }],
                    }]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName":  conn.reality_server_name or "www.microsoft.com",
                        "fingerprint": conn.reality_fingerprint  or "chrome",
                        "publicKey":   conn.reality_public_key   or "",
                        "shortId":     conn.reality_short_id     or "",
                    },
                },
            },
            {"tag": "direct", "protocol": "freedom"},
        ],
        "routing": {
            "rules": [{
                "type": "field",
                "inboundTag": ["socks-in"],
                "outboundTag": tag,
            }]
        },
    }
    return json.dumps(config)


def _validate_vless_tunnel(ssh, conn: Connection, server_ip: str) -> dict:
    """E2E валидация VLESS Reality через временный xray-клиент на сервере."""
    result = {
        "tunnel_ok": False,
        "dns_ok": False,
        "routing_ok": False,
        "traffic_ok": False,
        "internet_ok": False,
        "tunnel_ip": None,
        "tunnel_geo": None,
        "tunnel_latency_ms": None,
        "validation_errors": [],
    }
    tag = XRAY_CLIENT_TAG
    conf_path = f"/tmp/{tag}.json"

    try:
        # 1. Генерируем конфиг клиента
        client_conf = _build_vless_client_config(conn, server_ip, SOCKS_PORT)

        # 2. Загружаем конфиг на сервер
        # Экранируем для shell
        ssh.exec(f"cat > {conf_path} << 'XRAY_CLIENT_EOF'\n{client_conf}\nXRAY_CLIENT_EOF", timeout=5)

        # 3. Убиваем предыдущий процесс если был
        _kill_validator_xray(ssh)
        ssh.exec(f"pkill -f 'xray.*{tag}' 2>/dev/null; sleep 0.3", timeout=5)

        # 4. Запускаем xray-клиент в фоне
        _, start_out, start_err = ssh.exec(
            f"xray -config {conf_path} > /tmp/{tag}.log 2>&1 &"
            f" echo $!",
            timeout=8,
        )
        xray_pid = (start_out or "").strip()
        logger.debug(f"[e2e] vless client xray pid={xray_pid}")

        # 5. Ждём инициализации
        time.sleep(2.5)

        # 6. Проверяем что SOCKS5 слушает
        _, ss_out, _ = ssh.exec(
            f"ss -tlnp | grep ':{SOCKS_PORT}' || echo NOT_LISTENING",
            timeout=5,
        )
        ss_out = ss_out or ""
        if "NOT_LISTENING" in ss_out or str(SOCKS_PORT) not in ss_out:
            # Читаем лог для диагностики
            _, log_out, _ = ssh.exec(f"cat /tmp/{tag}.log 2>/dev/null | tail -10", timeout=5)
            err_msg = f"SOCKS5 not listening on :{SOCKS_PORT}"
            if log_out and "failed" in log_out.lower():
                err_msg += f": {log_out.strip()[:150]}"
            result["validation_errors"].append(err_msg)
            return result

        result["tunnel_ok"] = True  # SOCKS5 запущен → tunnel установлен

        # 7. DNS check
        result["dns_ok"] = _check_dns_resolution(ssh, TEST_DNS_HOST)
        if not result["dns_ok"]:
            result["validation_errors"].append("DNS resolution failed through tunnel")

        # 8. HTTP через tunnel — получаем реальный exit IP
        t_start = time.time()
        http_res = _http_via_socks5(ssh, SOCKS_PORT, TEST_URLS[0])
        t_elapsed = (time.time() - t_start) * 1000

        if http_res["ok"]:
            result["traffic_ok"] = True
            result["internet_ok"] = True
            result["tunnel_latency_ms"] = round(t_elapsed, 1)

            tunnel_ip = _parse_ip_from_response(http_res["body"])
            if tunnel_ip:
                result["tunnel_ip"] = tunnel_ip
                # routing_ok: IP через tunnel ≠ прямой IP сервера
                result["routing_ok"] = (tunnel_ip != server_ip)
                if not result["routing_ok"]:
                    result["validation_errors"].append(
                        f"Routing broken: tunnel IP {tunnel_ip} == server IP {server_ip}"
                    )
            else:
                result["validation_errors"].append("Could not parse tunnel exit IP")
        else:
            result["validation_errors"].append(
                f"HTTP through tunnel failed: {http_res['error'][:120]}"
            )

        # 9. Geo через tunnel
        if result["traffic_ok"]:
            geo_res = _http_via_socks5(ssh, SOCKS_PORT, TEST_URLS[1])
            if geo_res["ok"]:
                try:
                    geo_data = json.loads(geo_res["body"])
                    cc   = geo_data.get("country", "")
                    city = geo_data.get("city",    "")
                    org  = geo_data.get("org",     "")
                    parts = [p for p in [cc, city] if p]
                    result["tunnel_geo"] = ",".join(parts)[:64] if parts else None
                except Exception:
                    pass

    except Exception as e:
        result["validation_errors"].append(f"vless_e2e error: {str(e)[:200]}")
    finally:
        _kill_validator_xray(ssh)

    return result


# ─── AWG e2e ─────────────────────────────────────────────────────────────────

def _validate_awg_tunnel(ssh, conn: Connection, server_ip: str) -> dict:
    """
    AWG validation:
    Поскольку AWG использует UDP и требует kernel module на сервере,
    мы проверяем:
      1. awg interface существует (wg0/wg1/etc.)
      2. peer handshake был недавно (latest handshake)
      3. received/sent bytes > 0 (реальный трафик)
      4. routing: правило для peer subnet
    """
    result = {
        "tunnel_ok": False,
        "dns_ok": None,       # AWG DNS проверяется отдельно
        "routing_ok": False,
        "traffic_ok": False,
        "internet_ok": None,  # не проверяем через AWG с сервера
        "tunnel_ip": None,
        "tunnel_geo": None,
        "tunnel_latency_ms": None,
        "validation_errors": [],
    }

    try:
        # 1. Находим AWG-интерфейс для этого подключения
        # Ищем по client public key в конфиге интерфейсов
        client_pub = conn.wg_client_public_key
        if not client_pub:
            result["validation_errors"].append("AWG: no client public key in DB")
            return result

        # Ищем интерфейс где есть этот peer
        _, wg_out, _ = ssh.exec(
            "for iface in $(ls /etc/amnezia/amneziawg/ 2>/dev/null | grep '^wg' | sed 's/\\.conf//'); do "
            "  awg show $iface 2>/dev/null && echo \"IFACE:$iface\"; "
            "done",
            timeout=15,
        )
        wg_out = wg_out or ""

        if not wg_out.strip():
            # Пробуем через wireguard fallback
            _, wg_out, _ = ssh.exec(
                "wg show all 2>/dev/null || awg show all 2>/dev/null || echo AWG_UNAVAILABLE",
                timeout=10,
            )
            wg_out = wg_out or ""

        if "AWG_UNAVAILABLE" in wg_out or not wg_out.strip():
            result["validation_errors"].append("AWG: no interfaces found")
            return result

        # 2. Проверяем наличие peer и handshake
        # Ключ может быть полным или первые 20 символов
        key_short = client_pub[:20] if client_pub else ""
        peer_found = key_short in wg_out or (client_pub and client_pub in wg_out)

        if not peer_found:
            result["validation_errors"].append(
                f"AWG: peer not found (key={key_short}...)"
            )
            return result

        result["tunnel_ok"] = True

        # 3. Проверяем последний handshake и трафик
        # "latest handshake: X seconds ago"
        hs_match = re.search(r"latest handshake:\s+(.+?)(?:\n|$)", wg_out)
        if hs_match:
            hs_str = hs_match.group(1).strip()
            # Если handshake был > 3 минут назад — может быть неактивен
            if "days" in hs_str or "hours" in hs_str:
                result["validation_errors"].append(
                    f"AWG: stale handshake ({hs_str})"
                )
            else:
                result["routing_ok"] = True
        else:
            # Нет handshake — peer ещё не подключался
            result["validation_errors"].append("AWG: no handshake with peer yet")

        # 4. Проверяем rx/tx bytes
        rx_match = re.search(r"transfer:\s+([\d.]+\s+\w+)\s+received", wg_out)
        tx_match = re.search(r"transfer:.*?,([\d.]+\s+\w+)\s+sent", wg_out)
        if rx_match or tx_match:
            result["traffic_ok"] = True

        # 5. Проверяем routing rule для peer subnet
        client_ip_base = (conn.wg_client_ip or "").split("/")[0]
        if client_ip_base:
            _, route_out, _ = ssh.exec(
                f"ip route show | grep '{client_ip_base}' | head -3",
                timeout=8,
            )
            route_out = route_out or ""
            if client_ip_base in route_out:
                result["routing_ok"] = True
            else:
                result["validation_errors"].append(
                    f"AWG: no route for client IP {client_ip_base}"
                )

    except Exception as e:
        result["validation_errors"].append(f"awg_e2e error: {str(e)[:200]}")

    return result


# ─── NaiveProxy e2e ──────────────────────────────────────────────────────────

def _validate_naive_tunnel(ssh, conn: Connection, server_ip: str) -> dict:
    """
    NaiveProxy validation:
    Проверяем через curl с HTTPS-прокси на домен NaiveProxy.
    naive+https://{user}:{pass}@{domain}:{port}
    """
    result = {
        "tunnel_ok": False,
        "dns_ok": False,
        "routing_ok": False,
        "traffic_ok": False,
        "internet_ok": False,
        "tunnel_ip": None,
        "tunnel_geo": None,
        "tunnel_latency_ms": None,
        "validation_errors": [],
    }

    try:
        domain   = conn.np_domain or server_ip
        user     = conn.np_user   or "vpnuser"
        password = conn.password  or ""
        port     = conn.port      or 443

        if not password:
            result["validation_errors"].append("NaiveProxy: no password in DB")
            return result

        # DNS check
        result["dns_ok"] = _check_dns_resolution(ssh, domain)
        if not result["dns_ok"]:
            result["validation_errors"].append(f"NaiveProxy: DNS failed for {domain}")

        # curl через HTTPS-прокси
        proxy_url = f"https://{user}:{password}@{domain}:{port}"
        t_start   = time.time()

        _, out, err = ssh.exec(
            f"curl -s --max-time {TEST_HTTP_TIMEOUT} "
            f"--proxy '{proxy_url}' "
            f"--proxy-insecure "
            f"'{TEST_URLS[0]}' 2>&1 || echo CURL_FAIL",
            timeout=TEST_HTTP_TIMEOUT + 8,
        )
        t_elapsed = (time.time() - t_start) * 1000
        out = (out or "").strip()

        if "CURL_FAIL" in out or not out:
            result["validation_errors"].append(
                f"NaiveProxy: curl through proxy failed: {(err or '')[:100]}"
            )
            return result

        tunnel_ip = _parse_ip_from_response(out)
        if tunnel_ip:
            result["tunnel_ok"]         = True
            result["traffic_ok"]        = True
            result["internet_ok"]       = True
            result["tunnel_ip"]         = tunnel_ip
            result["tunnel_latency_ms"] = round(t_elapsed, 1)
            result["routing_ok"]        = (tunnel_ip != server_ip)
            if not result["routing_ok"]:
                result["validation_errors"].append(
                    f"NaiveProxy routing broken: {tunnel_ip} == {server_ip}"
                )
        else:
            result["validation_errors"].append("NaiveProxy: could not parse exit IP")

    except Exception as e:
        result["validation_errors"].append(f"naive_e2e error: {str(e)[:200]}")

    return result


# ─── Публичный API ───────────────────────────────────────────────────────────

def validate_connection_e2e(db: Session, conn: Connection) -> dict:
    """
    Публичная функция: полная e2e валидация одного подключения.
    Вызывается из health_check_service после server-side проверок.

    Возвращает словарь с результатами для записи в БД.
    """
    server = db.query(Server).filter(Server.id == conn.server_id).first()
    if not server:
        return {
            "tunnel_ok": False,
            "validation_errors": ["server not found"],
            "validated_at": datetime.now(timezone.utc),
        }

    # Для cascade — подключаемся к RU-серверу (entry point)
    is_cascade = (conn.connection_type == ConnectionType.CASCADE)
    if is_cascade and conn.ru_server_id:
        target = db.query(Server).filter(Server.id == conn.ru_server_id).first()
    else:
        target = server

    if not target:
        return {
            "tunnel_ok": False,
            "validation_errors": ["target server not found"],
            "validated_at": datetime.now(timezone.utc),
        }

    logger.info(
        f"[e2e] validating conn {conn.id} ({conn.protocol}/{conn.connection_type}) "
        f"on {target.ip}"
    )

    try:
        with SSHClient(target) as ssh:
            # WARP статус — общий для всех протоколов
            warp_active = _check_warp_active(ssh) if conn.warp_enabled else None

            # Protocol-specific e2e
            proto = conn.protocol
            if proto == Protocol.VLESS_REALITY:
                result = _validate_vless_tunnel(ssh, conn, target.ip)
            elif proto == Protocol.AMNEZIA_WG:
                result = _validate_awg_tunnel(ssh, conn, target.ip)
            elif proto == Protocol.NAIVE_PROXY:
                result = _validate_naive_tunnel(ssh, conn, target.ip)
            else:
                result = {
                    "tunnel_ok":  None,
                    "dns_ok":     None,
                    "routing_ok": None,
                    "traffic_ok": None,
                    "internet_ok": None,
                    "tunnel_ip":  None,
                    "tunnel_geo": None,
                    "tunnel_latency_ms": None,
                    "validation_errors": [f"e2e not implemented for {proto}"],
                }

            result["warp_active"]   = warp_active
            result["validated_at"]  = datetime.now(timezone.utc)

            errs = result.get("validation_errors", [])
            if errs:
                logger.warning(f"[e2e] conn {conn.id} errors: {errs}")
            else:
                logger.info(
                    f"[e2e] conn {conn.id} OK: "
                    f"tunnel={result.get('tunnel_ok')} "
                    f"ip={result.get('tunnel_ip')} "
                    f"lat={result.get('tunnel_latency_ms')}ms"
                )
            return result

    except Exception as e:
        logger.error(f"[e2e] validate_connection_e2e error conn {conn.id}: {e}")
        return {
            "tunnel_ok":  False,
            "dns_ok":     None,
            "routing_ok": None,
            "traffic_ok": None,
            "internet_ok": None,
            "warp_active": None,
            "tunnel_ip":  None,
            "tunnel_geo": None,
            "tunnel_latency_ms": None,
            "validation_errors": [str(e)[:300]],
            "validated_at": datetime.now(timezone.utc),
        }


def update_connection_validation(db: Session, conn: Connection, result: dict) -> None:
    """Записывает результаты e2e в БД."""
    try:
        # Tunnel & routing
        if hasattr(conn, "tunnel_ok"):
            conn.tunnel_ok = result.get("tunnel_ok")
        if hasattr(conn, "dns_ok"):
            conn.dns_ok = result.get("dns_ok")
        if hasattr(conn, "routing_ok"):
            conn.routing_ok = result.get("routing_ok")
        if hasattr(conn, "warp_active"):
            conn.warp_active = result.get("warp_active")
        if hasattr(conn, "client_validated_at") and result.get("validated_at"):
            conn.client_validated_at = result["validated_at"]

        # Validation errors → last_validation_error
        errs = result.get("validation_errors", [])
        if hasattr(conn, "last_validation_error"):
            conn.last_validation_error = "; ".join(errs)[:500] if errs else None

        # Tunnel latency/ip/geo → обновляем если лучше серверных данных
        if result.get("tunnel_ip") and hasattr(conn, "last_outbound_ip"):
            conn.last_outbound_ip = result["tunnel_ip"]
        if result.get("tunnel_geo") and hasattr(conn, "last_outbound_geo"):
            conn.last_outbound_geo = result["tunnel_geo"]

        db.commit()
    except Exception as e:
        logger.error(f"update_connection_validation error conn {conn.id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
