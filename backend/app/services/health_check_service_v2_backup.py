"""
Health Check Service — периодические проверки состояния VPN подключений.

Проверяет (по убыванию важности):
  1. xray.service alive         (systemctl is-active)
  2. Порт слушается             (ss -tlnp)
  3. Outbound internet          (curl api.ipify.org)
  4. Reality TLS handshake      (openssl s_client — только для VLESS)

Статусная модель:
  HEALTHY   — всё ОК: xray active + порт listening + TLS handshake OK
  DEGRADED  — частично работает: xray active + порт listening, но TLS или outbound под вопросом
  BROKEN    — не работает: xray down или порт не слушается

  MAX_FAILURES_BEFORE_BROKEN (=2) последовательных BROKEN → меняем ConnectionStatus на ERROR.
  При recovery (HEALTHY/DEGRADED) → восстанавливаем ConnectionStatus.ACTIVE.

Запускается в фоновом потоке при старте бэкенда (lifespan).
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.connection import Connection, Protocol, ConnectionType, ConnectionStatus
from app.models.server import Server
from app.services.ssh_service import SSHClient

logger = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

HEALTH_CHECK_INTERVAL      = 300   # секунды между циклами
HEALTH_CHECK_SSH_TIMEOUT   = 15    # таймаут каждой SSH-команды
MAX_FAILURES_BEFORE_BROKEN = 2     # сколько подряд BROKEN → статус ERROR
HEALTH_STATUSES = ("HEALTHY", "DEGRADED", "BROKEN")

# Глобальный state фонового потока
_stop_event    = threading.Event()
_health_thread: Optional[threading.Thread] = None

# Счётчик последовательных ошибок per-connection (в памяти, не в БД)
# { conn_id: int }
_failure_counts: dict = {}


# ─── Внутренние проверки ─────────────────────────────────────────────────────

def _check_service_and_port(ssh, port: int, proto: str = "tcp") -> dict:
    """Базовые проверки: xray alive + порт listening + outbound curl."""
    result = {
        "xray_active":   False,
        "port_listening": False,
        "outbound_ok":   False,
        "outbound_ip":   None,
        "errors":        [],
    }
    try:
        # 1. xray service
        _, xray_st, _ = ssh.exec(
            "systemctl is-active xray 2>/dev/null || echo unknown",
            timeout=HEALTH_CHECK_SSH_TIMEOUT,
        )
        xray_st = xray_st.strip()
        result["xray_active"] = (xray_st == "active")
        if not result["xray_active"]:
            result["errors"].append(f"xray={xray_st}")

        # 2. Порт
        flag = "" if proto == "tcp" else "u"
        _, ss_out, _ = ssh.exec(
            f"ss -t{flag}lnp 2>/dev/null | grep ':{port}' || echo NOT_LISTENING",
            timeout=HEALTH_CHECK_SSH_TIMEOUT,
        )
        result["port_listening"] = (str(port) in ss_out and "NOT_LISTENING" not in ss_out)
        if not result["port_listening"]:
            result["errors"].append(f"port {port}/{proto} not listening")

        # 3. Outbound
        _, curl_out, _ = ssh.exec(
            "curl -s --max-time 8 https://api.ipify.org 2>/dev/null || echo CURL_FAIL",
            timeout=HEALTH_CHECK_SSH_TIMEOUT + 10,
        )
        curl_out = curl_out.strip()
        if curl_out and curl_out != "CURL_FAIL" and "." in curl_out:
            result["outbound_ok"] = True
            result["outbound_ip"] = curl_out[:20]
        else:
            result["errors"].append("outbound unavailable")

    except Exception as e:
        result["errors"].append(f"ssh_error: {str(e)[:80]}")

    return result


def _check_reality_tls(ssh, server_ip: str, port: int, sni: str) -> dict:
    """
    Reality TLS handshake validation через openssl s_client.

    Возвращает:
      tls_ok:      bool    — handshake прошёл
      tls_status:  str     — CONNECTED | REFUSED | TIMEOUT | UNAVAILABLE | UNKNOWN
      tls_detail:  str     — краткое описание результата
    """
    result = {"tls_ok": False, "tls_status": "UNKNOWN", "tls_detail": ""}

    try:
        _, out, _ = ssh.exec(
            f"echo | timeout 8 openssl s_client "
            f"-connect {server_ip}:{port} "
            f"-servername {sni} "
            f"-tls1_3 2>&1 | head -15 || echo TLS_UNAVAILABLE",
            timeout=HEALTH_CHECK_SSH_TIMEOUT,
        )
        out = out or ""

        if "TLS_UNAVAILABLE" in out or not out.strip():
            result["tls_status"]  = "UNAVAILABLE"
            result["tls_detail"]  = "openssl недоступен на сервере"
            # Не считаем это ошибкой — openssl может отсутствовать
            result["tls_ok"] = None  # None = не проверялось

        elif any(x in out for x in ["CONNECTED", "Certificate chain", "SSL handshake"]):
            result["tls_ok"]     = True
            result["tls_status"] = "CONNECTED"
            result["tls_detail"] = f"TLS handshake OK (SNI={sni})"

        elif "Connection refused" in out or "connect: Connection" in out:
            result["tls_ok"]     = False
            result["tls_status"] = "REFUSED"
            result["tls_detail"] = "порт недоступен (Connection refused)"

        elif "timed out" in out.lower() or "timeout" in out.lower():
            result["tls_ok"]     = False
            result["tls_status"] = "TIMEOUT"
            result["tls_detail"] = "TLS timeout — порт может быть заблокирован"

        else:
            # Неизвестный ответ — не считаем фатальным
            result["tls_status"] = "UNKNOWN"
            result["tls_detail"] = out.strip()[:100].replace("\n", " ")
            result["tls_ok"]     = None

    except Exception as e:
        result["tls_status"] = "ERROR"
        result["tls_detail"] = str(e)[:80]

    return result


def _classify_health(base: dict, tls: Optional[dict], proto: Protocol) -> str:
    """
    Определяет итоговый статус подключения: HEALTHY / DEGRADED / BROKEN.

    BROKEN   — xray down ИЛИ порт не слушается
    DEGRADED — всё работает, но TLS handshake провалился (Reality не отвечает)
               или outbound недоступен
    HEALTHY  — всё OK
    """
    if proto == Protocol.AMNEZIA_WG:
        # AWG: только порт (UDP), xray не используется
        return "HEALTHY" if base["port_listening"] else "BROKEN"

    # VLESS / NaiveProxy
    if not base["xray_active"] or not base["port_listening"]:
        return "BROKEN"

    # TLS check (только для VLESS+Reality)
    tls_failed = False
    if tls and proto == Protocol.VLESS_REALITY:
        if tls["tls_ok"] is False:  # явный False — проверка прошла и завалилась
            tls_failed = True

    if tls_failed or not base["outbound_ok"]:
        return "DEGRADED"

    return "HEALTHY"


# ─── Публичные функции ────────────────────────────────────────────────────────

def check_connection_health(db: Session, conn: Connection) -> dict:
    """
    Полная проверка здоровья подключения.

    Возвращает:
      health_status: HEALTHY | DEGRADED | BROKEN
      ok:            bool (True если HEALTHY или DEGRADED)
      xray_active:   bool
      port_listening: bool
      outbound_ok:   bool
      outbound_ip:   str | None
      tls_status:    str (CONNECTED|REFUSED|TIMEOUT|UNAVAILABLE|UNKNOWN|None)
      tls_detail:    str
      errors:        list[str]
      server_ip:     str
    """
    server = db.query(Server).filter(Server.id == conn.server_id).first()
    if not server:
        return {"ok": False, "health_status": "BROKEN", "reason": "server not found"}

    is_cascade = (conn.connection_type == ConnectionType.CASCADE)
    if is_cascade and conn.ru_server_id:
        target_server = db.query(Server).filter(Server.id == conn.ru_server_id).first()
    else:
        target_server = server

    if not target_server:
        return {"ok": False, "health_status": "BROKEN", "reason": "target server not found"}

    try:
        proto_str = "udp" if conn.protocol == Protocol.AMNEZIA_WG else "tcp"

        with SSHClient(target_server) as ssh:
            base = _check_service_and_port(ssh, conn.port, proto_str)

            # Reality TLS проверяем только если xray слушает
            tls_result = None
            if conn.protocol == Protocol.VLESS_REALITY and base["port_listening"]:
                sni = conn.reality_server_name or "www.microsoft.com"
                tls_result = _check_reality_tls(ssh, target_server.ip, conn.port, sni)

        health_status = _classify_health(base, tls_result, conn.protocol)

        return {
            "ok":            health_status != "BROKEN",
            "health_status": health_status,
            "xray_active":   base["xray_active"],
            "port_listening": base["port_listening"],
            "outbound_ok":   base["outbound_ok"],
            "outbound_ip":   base["outbound_ip"],
            "tls_status":    tls_result["tls_status"] if tls_result else None,
            "tls_detail":    tls_result["tls_detail"] if tls_result else None,
            "errors":        base["errors"],
            "server_ip":     target_server.ip,
        }

    except Exception as e:
        logger.warning(f"Health check SSH error for conn {conn.id}: {e}")
        return {
            "ok":            False,
            "health_status": "BROKEN",
            "reason":        str(e),
            "errors":        [str(e)],
        }


def _update_connection_health(db: Session, conn: Connection, health: dict) -> None:
    """
    Обновляет состояние Connection в БД по результату health-check.

    Логика статусов:
    - HEALTHY/DEGRADED → сбрасываем failure_count, восстанавливаем ACTIVE если был ERROR
    - BROKEN × N раз подряд → меняем на ERROR (N = MAX_FAILURES_BEFORE_BROKEN)
    """
    global _failure_counts
    try:
        now      = datetime.now(timezone.utc)
        ts       = now.strftime("%H:%M:%S")
        h_status = health.get("health_status", "BROKEN")

        # last_check поля если есть в модели
        if hasattr(conn, "last_check_at"):
            conn.last_check_at = now
        if hasattr(conn, "last_check_ok"):
            conn.last_check_ok = (h_status != "BROKEN")

        # Лаконичная запись в setup_log
        tls_part = ""
        if health.get("tls_status"):
            tls_part = f",tls={health['tls_status']}"
        net_part = f",net={health.get('outbound_ip') or 'no'}"

        if h_status == "HEALTHY":
            note = f"[HC:{ts}:HEALTHY:xray=ok,port=ok{tls_part}{net_part}]"
        elif h_status == "DEGRADED":
            issues = " ".join(health.get("errors", []))[:60]
            note = f"[HC:{ts}:DEGRADED:{issues}{tls_part}]"
        else:  # BROKEN
            issues = " ".join(health.get("errors", [health.get("reason", "?")]))[:80]
            note = f"[HC:{ts}:BROKEN:{issues}]"

        # Ротация HC-записей в setup_log (храним последние 5)
        cur_log     = conn.setup_log or ""
        hc_lines    = [l for l in cur_log.split("\n") if l.startswith("[HC:")]
        other_lines = [l for l in cur_log.split("\n") if not l.startswith("[HC:")]
        hc_lines    = hc_lines[-4:] + [note]
        conn.setup_log = "\n".join(other_lines + hc_lines).strip()

        # ── Счётчик ошибок и смена статуса ───────────────────────────────────
        cid = conn.id

        if h_status == "BROKEN":
            _failure_counts[cid] = _failure_counts.get(cid, 0) + 1
            cnt = _failure_counts[cid]

            if cnt >= MAX_FAILURES_BEFORE_BROKEN and conn.status == ConnectionStatus.ACTIVE:
                conn.status = ConnectionStatus.ERROR
                logger.warning(
                    f"conn {cid} → ERROR after {cnt} BROKEN checks "
                    f"({conn.protocol}/{conn.connection_type})"
                )
        else:
            # HEALTHY или DEGRADED — сбрасываем счётчик
            prev = _failure_counts.pop(cid, 0)
            if prev > 0:
                logger.info(f"conn {cid} failure_count reset (was {prev})")

            if h_status == "HEALTHY" and conn.status == ConnectionStatus.ERROR:
                conn.status = ConnectionStatus.ACTIVE
                logger.info(f"conn {cid} RECOVERED → ACTIVE")
            # DEGRADED не восстанавливает автоматически — требует ручного redeploy

        db.commit()

    except Exception as e:
        logger.error(f"_update_connection_health error for conn {conn.id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ─── Цикл и воркер ───────────────────────────────────────────────────────────

def run_health_check_cycle() -> None:
    """Один полный цикл: проверяем все active+done подключения."""
    db = SessionLocal()
    try:
        connections = db.query(Connection).filter(
            Connection.is_active   == True,
            Connection.setup_status == "done",
        ).all()

        logger.info(f"Health check cycle: {len(connections)} connections")

        for conn in connections:
            if _stop_event.is_set():
                break
            try:
                health = check_connection_health(db, conn)
                _update_connection_health(db, conn, health)
                logger.debug(
                    f"  [{health['health_status']}] conn {conn.id} "
                    f"({conn.protocol}/{conn.connection_type}) "
                    f"tls={health.get('tls_status')} net={health.get('outbound_ip')}"
                )
            except Exception as e:
                logger.error(f"Health check error conn {conn.id}: {e}")

            time.sleep(2)   # пауза между проверками

    except Exception as e:
        logger.error(f"Health check cycle error: {e}")
    finally:
        db.close()


def _health_check_worker() -> None:
    """Фоновый поток."""
    logger.info(f"Health check worker started (interval={HEALTH_CHECK_INTERVAL}s)")
    _stop_event.wait(timeout=60)           # первый старт через 60 сек

    while not _stop_event.is_set():
        try:
            run_health_check_cycle()
        except Exception as e:
            logger.error(f"Health check worker error: {e}")
        _stop_event.wait(timeout=HEALTH_CHECK_INTERVAL)

    logger.info("Health check worker stopped")


# ─── Публичные lifecycle функции ─────────────────────────────────────────────

def start_health_check_worker() -> None:
    """Запускает воркер. Вызывается из lifespan FastAPI."""
    global _health_thread
    if _health_thread and _health_thread.is_alive():
        logger.warning("Health check worker already running")
        return
    _stop_event.clear()
    _health_thread = threading.Thread(
        target=_health_check_worker,
        name="health-check-worker",
        daemon=True,
    )
    _health_thread.start()
    logger.info("Health check worker thread started")


def stop_health_check_worker() -> None:
    """Останавливает воркер. Вызывается из lifespan shutdown."""
    global _health_thread
    _stop_event.set()
    if _health_thread:
        _health_thread.join(timeout=10)
        _health_thread = None
    logger.info("Health check worker stopped")


def get_connection_health_status(db: Session, connection_id: int) -> dict:
    """
    On-demand deep health check одного подключения.
    Используется API: GET /connections/{id}/health
    """
    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if not conn:
        return {"ok": False, "health_status": "BROKEN", "reason": "connection not found"}

    health = check_connection_health(db, conn)
    _update_connection_health(db, conn, health)
    return health
