"""
Health Check Service v3 — периодические проверки + latency/jitter/geo + auto-recovery.

Статусная модель:
  HEALTHY   — всё OK
  DEGRADED  — xray+порт работают, но TLS/outbound/packet_loss > 30% проблематичны
  BROKEN    — xray down или порт не слушается

MAX_FAILURES_BEFORE_BROKEN (=2) последовательных BROKEN → auto_recovery_service
"""
import json
import logging
import re
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

HEALTH_CHECK_INTERVAL      = 300
HEALTH_CHECK_SSH_TIMEOUT   = 15
MAX_FAILURES_BEFORE_BROKEN = 2
LATENCY_PING_TARGET        = "8.8.8.8"
LATENCY_PING_COUNT         = 5
PACKET_LOSS_DEGRADED_PCT   = 30.0

_stop_event    = threading.Event()
_health_thread: Optional[threading.Thread] = None
_failure_counts: dict = {}


# ─── Latency / jitter / packet loss ──────────────────────────────────────────

def _check_latency(ssh, target: str = LATENCY_PING_TARGET, count: int = LATENCY_PING_COUNT) -> dict:
    """Ping с сервера: latency_ms, jitter_ms, packet_loss_pct."""
    result = {"latency_ms": None, "jitter_ms": None, "packet_loss_pct": None, "ping_ok": False}
    try:
        _, out, _ = ssh.exec(
            f"ping -c {count} -W 3 {target} 2>&1 || echo PING_FAIL",
            timeout=HEALTH_CHECK_SSH_TIMEOUT + count * 3,
        )
        out = out or ""

        # rtt min/avg/max/mdev = 1.2/3.4/5.6/0.8 ms
        rtt_m = re.search(
            r"min/avg/max/(?:mdev|stddev)\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms",
            out,
        )
        if rtt_m:
            result["latency_ms"] = round(float(rtt_m.group(2)), 2)
            result["jitter_ms"]  = round(float(rtt_m.group(4)), 2)
            result["ping_ok"]    = True

        # X% packet loss
        loss_m = re.search(r"([\d.]+)%\s+packet loss", out)
        if loss_m:
            result["packet_loss_pct"] = round(float(loss_m.group(1)), 1)

    except Exception as e:
        logger.debug(f"_check_latency error: {e}")
    return result


# ─── Base checks + geo ────────────────────────────────────────────────────────

def _check_service_and_port(ssh, port: int, proto: str = "tcp") -> dict:
    """xray alive + порт listening + outbound IP + geo."""
    result = {
        "xray_active":    False,
        "port_listening": False,
        "outbound_ok":    False,
        "outbound_ip":    None,
        "outbound_geo":   None,
        "errors":         [],
    }
    try:
        # 1. xray
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

        # 3. Outbound IP + geo через ipapi.co
        _, curl_out, _ = ssh.exec(
            "curl -s --max-time 8 https://ipapi.co/json 2>/dev/null || echo CURL_FAIL",
            timeout=HEALTH_CHECK_SSH_TIMEOUT + 10,
        )
        curl_out = (curl_out or "").strip()
        if curl_out and curl_out != "CURL_FAIL" and curl_out.startswith("{"):
            try:
                geo_data = json.loads(curl_out)
                ip  = geo_data.get("ip", "")
                cc  = geo_data.get("country_code", "")
                cit = geo_data.get("city", "")
                if ip and "." in ip:
                    result["outbound_ok"]  = True
                    result["outbound_ip"]  = ip[:20]
                    result["outbound_geo"] = f"{cc},{cit}"[:64] if (cc or cit) else None
                else:
                    result["errors"].append("outbound: no IP in geo response")
            except Exception:
                result["errors"].append("outbound: geo JSON parse error")
        else:
            # Фоллбэк — просто ipify
            _, ip_out, _ = ssh.exec(
                "curl -s --max-time 8 https://api.ipify.org 2>/dev/null || echo CURL_FAIL",
                timeout=HEALTH_CHECK_SSH_TIMEOUT + 10,
            )
            ip_out = (ip_out or "").strip()
            if ip_out and ip_out != "CURL_FAIL" and "." in ip_out:
                result["outbound_ok"] = True
                result["outbound_ip"] = ip_out[:20]
            else:
                result["errors"].append("outbound unavailable")

    except Exception as e:
        result["errors"].append(f"ssh_error: {str(e)[:80]}")
    return result


def _check_reality_tls(ssh, server_ip: str, port: int, sni: str) -> dict:
    """Reality TLS handshake validation через openssl s_client."""
    result = {"tls_ok": False, "tls_status": "UNKNOWN", "tls_detail": ""}
    try:
        _, out, _ = ssh.exec(
            f"echo | timeout 8 openssl s_client "            f"-connect {server_ip}:{port} "            f"-servername {sni} "            f"-tls1_3 2>&1 | head -15 || echo TLS_UNAVAILABLE",
            timeout=HEALTH_CHECK_SSH_TIMEOUT,
        )
        out = out or ""
        if "TLS_UNAVAILABLE" in out or not out.strip():
            result["tls_status"] = "UNAVAILABLE"
            result["tls_detail"] = "openssl недоступен на сервере"
            result["tls_ok"]     = None
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
            result["tls_detail"] = "TLS timeout"
        else:
            result["tls_status"] = "UNKNOWN"
            result["tls_detail"] = out.strip()[:100].replace("\n", " ")
            result["tls_ok"]     = None
    except Exception as e:
        result["tls_status"] = "ERROR"
        result["tls_detail"] = str(e)[:80]
    return result


# ─── Классификация ────────────────────────────────────────────────────────────

def _classify_health(base: dict, tls: Optional[dict], latency: dict, proto) -> str:
    """HEALTHY / DEGRADED / BROKEN."""
    if proto == Protocol.AMNEZIA_WG:
        return "HEALTHY" if base["port_listening"] else "BROKEN"

    if not base["xray_active"] or not base["port_listening"]:
        return "BROKEN"

    tls_failed = False
    if tls and proto == Protocol.VLESS_REALITY:
        if tls["tls_ok"] is False:
            tls_failed = True

    high_loss = (
        latency.get("packet_loss_pct") is not None
        and latency["packet_loss_pct"] > PACKET_LOSS_DEGRADED_PCT
    )

    if tls_failed or not base["outbound_ok"] or high_loss:
        return "DEGRADED"

    return "HEALTHY"


# ─── Публичная проверка ───────────────────────────────────────────────────────

def check_connection_health(db: Session, conn: Connection) -> dict:
    """Полная проверка: base + TLS + latency/jitter/geo."""
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
            base        = _check_service_and_port(ssh, conn.port, proto_str)
            latency_res = _check_latency(ssh)

            tls_result = None
            if conn.protocol == Protocol.VLESS_REALITY and base["port_listening"]:
                sni = conn.reality_server_name or "www.microsoft.com"
                tls_result = _check_reality_tls(ssh, target_server.ip, conn.port, sni)

        health_status = _classify_health(base, tls_result, latency_res, conn.protocol)

        return {
            "ok":             health_status != "BROKEN",
            "health_status":  health_status,
            "xray_active":    base["xray_active"],
            "port_listening": base["port_listening"],
            "outbound_ok":    base["outbound_ok"],
            "outbound_ip":    base["outbound_ip"],
            "outbound_geo":   base["outbound_geo"],
            "latency_ms":     latency_res.get("latency_ms"),
            "jitter_ms":      latency_res.get("jitter_ms"),
            "packet_loss_pct": latency_res.get("packet_loss_pct"),
            "tls_status":     tls_result["tls_status"] if tls_result else None,
            "tls_detail":     tls_result["tls_detail"] if tls_result else None,
            "errors":         base["errors"],
            "server_ip":      target_server.ip,
        }

    except Exception as e:
        logger.warning(f"Health check SSH error for conn {conn.id}: {e}")
        return {
            "ok":            False,
            "health_status": "BROKEN",
            "reason":        str(e),
            "errors":        [str(e)],
        }


# ─── Запись в БД ──────────────────────────────────────────────────────────────

def _update_connection_health(db: Session, conn: Connection, health: dict) -> None:
    """Обновляет все health-поля Connection + вызывает auto_recovery при BROKEN×N."""
    global _failure_counts
    try:
        now      = datetime.now(timezone.utc)
        ts       = now.strftime("%H:%M:%S")
        h_status = health.get("health_status", "BROKEN")

        # ── Новые поля v3 ─────────────────────────────────────────────────────
        if hasattr(conn, "health_status"):
            conn.health_status = h_status
        if hasattr(conn, "last_check_at"):
            conn.last_check_at = now
        if hasattr(conn, "last_check_ok"):
            conn.last_check_ok = (h_status != "BROKEN")
        if hasattr(conn, "last_outbound_ip") and health.get("outbound_ip"):
            conn.last_outbound_ip = health["outbound_ip"]
        if hasattr(conn, "last_outbound_geo") and health.get("outbound_geo"):
            conn.last_outbound_geo = health["outbound_geo"]
        if hasattr(conn, "last_tls_status") and health.get("tls_status"):
            conn.last_tls_status = health["tls_status"]
        if hasattr(conn, "latency_ms") and health.get("latency_ms") is not None:
            conn.latency_ms = health["latency_ms"]
        if hasattr(conn, "jitter_ms") and health.get("jitter_ms") is not None:
            conn.jitter_ms = health["jitter_ms"]
        if hasattr(conn, "packet_loss_pct") and health.get("packet_loss_pct") is not None:
            conn.packet_loss_pct = health["packet_loss_pct"]
        if hasattr(conn, "last_active_at") and h_status != "BROKEN":
            conn.last_active_at = now

        # ── Лог в setup_log ───────────────────────────────────────────────────
        lat   = health.get("latency_ms")
        loss  = health.get("packet_loss_pct")
        tls_p = f",tls={health['tls_status']}" if health.get("tls_status") else ""
        net_p = f",net={health.get('outbound_ip') or 'no'}"
        lat_p = f",lat={lat}ms" if lat is not None else ""
        geo_p = f",geo={health.get('outbound_geo')}" if health.get("outbound_geo") else ""

        if h_status == "HEALTHY":
            note = f"[HC:{ts}:HEALTHY:xray=ok,port=ok{tls_p}{net_p}{lat_p}{geo_p}]"
        elif h_status == "DEGRADED":
            issues = " ".join(health.get("errors", []))[:60]
            note = f"[HC:{ts}:DEGRADED:{issues}{tls_p}{lat_p}]"
        else:
            issues = " ".join(health.get("errors", [health.get("reason", "?")]))[:80]
            note = f"[HC:{ts}:BROKEN:{issues}]"

        cur_log     = conn.setup_log or ""
        hc_lines    = [l for l in cur_log.split("\n") if l.startswith("[HC:")]
        other_lines = [l for l in cur_log.split("\n") if not l.startswith("[HC:")]
        hc_lines    = hc_lines[-4:] + [note]
        conn.setup_log = "\n".join(other_lines + hc_lines).strip()

        # ── Failure counter + auto-recovery ───────────────────────────────────
        cid = conn.id

        if h_status == "BROKEN":
            _failure_counts[cid] = _failure_counts.get(cid, 0) + 1
            cnt = _failure_counts[cid]
            logger.warning(f"conn {cid} BROKEN (count={cnt}/{MAX_FAILURES_BEFORE_BROKEN})")

            if cnt >= MAX_FAILURES_BEFORE_BROKEN:
                # Обновляем статус и коммитим до вызова recovery
                if conn.status == ConnectionStatus.ACTIVE:
                    conn.status = ConnectionStatus.ERROR
                db.commit()
                # Пытаемся авто-восстановление
                try:
                    from app.services import auto_recovery_service
                    recovery_result = auto_recovery_service.attempt_recovery(db, conn, health)
                    if recovery_result.get("recovered"):
                        _failure_counts[cid] = 0
                        logger.info(f"conn {cid} auto-recovered successfully")
                    else:
                        logger.warning(f"conn {cid} auto-recovery failed: {recovery_result.get('reason')}")
                except Exception as rec_err:
                    logger.error(f"auto_recovery_service error for conn {cid}: {rec_err}")
                return
        else:
            prev = _failure_counts.pop(cid, 0)
            if prev > 0:
                logger.info(f"conn {cid} failure_count reset (was {prev})")
            if h_status == "HEALTHY" and conn.status == ConnectionStatus.ERROR:
                conn.status = ConnectionStatus.ACTIVE
                logger.info(f"conn {cid} RECOVERED → ACTIVE")

        db.commit()

    except Exception as e:
        logger.error(f"_update_connection_health error conn {conn.id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ─── Цикл ────────────────────────────────────────────────────────────────────

def run_health_check_cycle() -> None:
    """Один полный цикл для всех active+done подключений."""
    db = SessionLocal()
    try:
        connections = db.query(Connection).filter(
            Connection.is_active    == True,
            Connection.setup_status == "done",
        ).all()
        logger.info(f"Health check cycle v3: {len(connections)} connections")

        for conn in connections:
            if _stop_event.is_set():
                break
            try:
                health = check_connection_health(db, conn)
                _update_connection_health(db, conn, health)
                logger.debug(
                    f"  [{health['health_status']}] conn {conn.id} "                    f"({conn.protocol}/{conn.connection_type}) "                    f"lat={health.get('latency_ms')}ms "                    f"loss={health.get('packet_loss_pct')}% "                    f"geo={health.get('outbound_geo')} "                    f"tls={health.get('tls_status')}"
                )
            except Exception as e:
                logger.error(f"Health check error conn {conn.id}: {e}")
            time.sleep(2)
    except Exception as e:
        logger.error(f"Health check cycle error: {e}")
    finally:
        db.close()


def _health_check_worker() -> None:
    logger.info(f"Health check worker v3 started (interval={HEALTH_CHECK_INTERVAL}s)")
    _stop_event.wait(timeout=60)
    while not _stop_event.is_set():
        try:
            run_health_check_cycle()
        except Exception as e:
            logger.error(f"Health check worker error: {e}")
        _stop_event.wait(timeout=HEALTH_CHECK_INTERVAL)
    logger.info("Health check worker v3 stopped")


# ─── Lifecycle ────────────────────────────────────────────────────────────────

def start_health_check_worker() -> None:
    global _health_thread
    if _health_thread and _health_thread.is_alive():
        logger.warning("Health check worker already running")
        return
    _stop_event.clear()
    _health_thread = threading.Thread(
        target=_health_check_worker,
        name="health-check-worker-v3",
        daemon=True,
    )
    _health_thread.start()
    logger.info("Health check worker v3 thread started")


def stop_health_check_worker() -> None:
    global _health_thread
    _stop_event.set()
    if _health_thread:
        _health_thread.join(timeout=10)
        _health_thread = None
    logger.info("Health check worker v3 stopped")


def get_connection_health_status(db: Session, connection_id: int) -> dict:
    """On-demand проверка одного подключения (API endpoint)."""
    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if not conn:
        return {"ok": False, "health_status": "BROKEN", "reason": "connection not found"}
    health = check_connection_health(db, conn)
    _update_connection_health(db, conn, health)
    return health
