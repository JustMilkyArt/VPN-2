"""
Health Check Service v4 — Full Observability + End-to-End Validation

Статусная модель:
  HEALTHY   — server OK + e2e tunnel работает + трафик проходит
  DEGRADED  — server OK, но e2e частично не работает (DNS/routing/loss>30%)
  BROKEN    — xray down / порт не слушает / tunnel не устанавливается

HEALTHY требует:
  ✅ xray_active = True
  ✅ port_listening = True
  ✅ tunnel_ok = True       (e2e tunnel установлен)
  ✅ routing_ok = True      (трафик идёт через VPN)
  ✅ packet_loss < 30%

DEGRADED:
  - server OK но e2e проблемы (DNS fail, routing loop, high packet loss)
  - TLS failed для VLESS

BROKEN:
  - xray не активен
  - порт не слушает
  - tunnel не устанавливается

E2E validation: запускается раз в N циклов (не каждые 5 минут)
чтобы не перегружать сервер временными xray-клиентами.
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

# ─── Константы ───────────────────────────────────────────────────────────────

HEALTH_CHECK_INTERVAL       = 300    # секунды между циклами
HEALTH_CHECK_SSH_TIMEOUT    = 15
MAX_FAILURES_BEFORE_BROKEN  = 2
LATENCY_PING_TARGET         = "8.8.8.8"
LATENCY_PING_COUNT          = 5
PACKET_LOSS_DEGRADED_PCT    = 30.0
E2E_EVERY_N_CYCLES          = 3      # e2e раз в 3 цикла (~15 мин)

_stop_event    = threading.Event()
_health_thread: Optional[threading.Thread] = None
_failure_counts: dict = {}
_cycle_counter: int   = 0           # глобальный счётчик циклов


# ─── Latency / jitter / packet loss ─────────────────────────────────────────

def _check_latency(ssh, target: str = LATENCY_PING_TARGET,
                   count: int = LATENCY_PING_COUNT) -> dict:
    """Ping с сервера: latency_ms, jitter_ms, packet_loss_pct."""
    result = {"latency_ms": None, "jitter_ms": None,
              "packet_loss_pct": None, "ping_ok": False}
    try:
        _, out, _ = ssh.exec(
            f"ping -c {count} -W 3 {target} 2>&1 || echo PING_FAIL",
            timeout=HEALTH_CHECK_SSH_TIMEOUT + count * 3,
        )
        out = out or ""
        rtt_m = re.search(
            r"min/avg/max/(?:mdev|stddev)\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms",
            out,
        )
        if rtt_m:
            result["latency_ms"] = round(float(rtt_m.group(2)), 2)
            result["jitter_ms"]  = round(float(rtt_m.group(4)), 2)
            result["ping_ok"]    = True
        loss_m = re.search(r"([\d.]+)%\s+packet loss", out)
        if loss_m:
            result["packet_loss_pct"] = round(float(loss_m.group(1)), 1)
    except Exception as e:
        logger.debug(f"_check_latency error: {e}")
    return result


# ─── Server-side checks ──────────────────────────────────────────────────────

def _check_service_and_port(ssh, port: int, proto: str = "tcp",
                             protocol_enum=None) -> dict:
    """Полные server-side проверки: xray/caddy, порт, outbound IP, geo, WARP."""
    result = {
        "xray_active":    False,
        "port_listening": False,
        "outbound_ok":    False,
        "outbound_ip":    None,
        "outbound_geo":   None,
        "warp_active":    None,
        "errors":         [],
    }
    try:
        # 1. xray (для NaiveProxy — caddy)
        is_naive = (protocol_enum == Protocol.NAIVE_PROXY)
        if is_naive:
            _, svc_st, _ = ssh.exec(
                "systemctl is-active caddy 2>/dev/null || echo unknown",
                timeout=HEALTH_CHECK_SSH_TIMEOUT,
            )
            result["xray_active"] = (svc_st.strip() == "active")
            if not result["xray_active"]:
                # Caddy может работать без systemd
                _, caddy_ps, _ = ssh.exec(
                    "pgrep -x caddy > /dev/null 2>&1 && echo active || echo inactive",
                    timeout=5,
                )
                result["xray_active"] = (caddy_ps.strip() == "active")
        else:
            _, xray_st, _ = ssh.exec(
                "systemctl is-active xray 2>/dev/null || echo unknown",
                timeout=HEALTH_CHECK_SSH_TIMEOUT,
            )
            result["xray_active"] = (xray_st.strip() == "active")
        if not result["xray_active"]:
            result["errors"].append("xray/caddy not active")

        # 2. Порт
        flag = "u" if proto == "udp" else ""
        _, ss_out, _ = ssh.exec(
            f"ss -t{flag}lnp 2>/dev/null | grep ':{port}' || echo NOT_LISTENING",
            timeout=HEALTH_CHECK_SSH_TIMEOUT,
        )
        result["port_listening"] = (
            str(port) in (ss_out or "") and
            "NOT_LISTENING" not in (ss_out or "")
        )
        if not result["port_listening"]:
            result["errors"].append(f"port {port}/{proto} not listening")

        # 3. Outbound IP + geo (ipapi.co)
        _, curl_out, _ = ssh.exec(
            "curl -s --max-time 8 https://ipapi.co/json 2>/dev/null || echo CURL_FAIL",
            timeout=HEALTH_CHECK_SSH_TIMEOUT + 10,
        )
        curl_out = (curl_out or "").strip()
        if curl_out and curl_out != "CURL_FAIL" and curl_out.startswith("{"):
            try:
                geo = json.loads(curl_out)
                ip  = geo.get("ip", "")
                cc  = geo.get("country_code", "")
                cit = geo.get("city", "")
                if ip and "." in ip:
                    result["outbound_ok"]  = True
                    result["outbound_ip"]  = ip[:20]
                    result["outbound_geo"] = f"{cc},{cit}"[:64] if (cc or cit) else None
                else:
                    result["errors"].append("outbound: no IP in geo response")
            except Exception:
                result["errors"].append("outbound: geo JSON parse error")
        else:
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

        # 4. WARP статус
        _, warp_out, _ = ssh.exec(
            "warp-cli status 2>/dev/null || echo WARP_UNAVAILABLE",
            timeout=8,
        )
        warp_out = warp_out or ""
        if "WARP_UNAVAILABLE" in warp_out or "command not found" in warp_out:
            result["warp_active"] = None  # не установлен
        else:
            result["warp_active"] = "Connected" in warp_out

    except Exception as e:
        result["errors"].append(f"ssh_error: {str(e)[:80]}")
    return result


def _check_reality_tls(ssh, server_ip: str, port: int, sni: str) -> dict:
    """Reality TLS handshake через openssl s_client."""
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
            result["tls_status"] = "UNAVAILABLE"
            result["tls_detail"] = "openssl недоступен"
            result["tls_ok"]     = None
        elif any(x in out for x in ["CONNECTED", "Certificate chain", "SSL handshake"]):
            result["tls_ok"]     = True
            result["tls_status"] = "CONNECTED"
            result["tls_detail"] = f"TLS OK (SNI={sni})"
        elif "Connection refused" in out or "connect: Connection" in out:
            result["tls_ok"]     = False
            result["tls_status"] = "REFUSED"
            result["tls_detail"] = "порт недоступен"
        elif "timed out" in out.lower():
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


# ─── Классификация (новая модель) ─────────────────────────────────────────────

def _classify_health(base: dict, tls: Optional[dict], latency: dict,
                     proto, e2e: Optional[dict] = None) -> str:
    """
    Новая HEALTHY-модель v4:

    BROKEN:
      - xray не активен
      - порт не слушает
      - tunnel_ok is False (e2e провалился)

    DEGRADED:
      - server OK но TLS failed (только VLESS)
      - outbound недоступен
      - packet_loss > 30%
      - tunnel_ok is None (e2e не запускался / ошибка)
      - routing_ok = False (трафик не через VPN)

    HEALTHY:
      - всё выше OK
      - если e2e запускался: tunnel_ok=True, routing_ok=True

    AWG отдельная логика (UDP, нет TLS):
      HEALTHY если port_listening
      BROKEN если port не слушает
    """
    if proto == Protocol.AMNEZIA_WG:
        if not base["port_listening"]:
            return "BROKEN"
        # Если e2e запускался — учитываем
        if e2e is not None:
            if e2e.get("tunnel_ok") is False:
                return "BROKEN"
            if e2e.get("routing_ok") is False:
                return "DEGRADED"
        return "HEALTHY"

    # Основные server-side checks
    if not base["xray_active"] or not base["port_listening"]:
        return "BROKEN"

    # E2E tunnel validation
    if e2e is not None:
        if e2e.get("tunnel_ok") is False:
            return "BROKEN"      # tunnel не устанавливается
        if e2e.get("routing_ok") is False:
            return "DEGRADED"    # трафик не через VPN

    # TLS check (только VLESS)
    tls_failed = False
    if tls and proto == Protocol.VLESS_REALITY:
        if tls["tls_ok"] is False:
            tls_failed = True

    # Packet loss
    high_loss = (
        latency.get("packet_loss_pct") is not None and
        latency["packet_loss_pct"] > PACKET_LOSS_DEGRADED_PCT
    )

    if tls_failed or not base["outbound_ok"] or high_loss:
        return "DEGRADED"

    # e2e не запускался — HEALTHY по server-side данным
    return "HEALTHY"


# ─── Полная проверка одного подключения ──────────────────────────────────────

def check_connection_health(db: Session, conn: Connection,
                            run_e2e: bool = False) -> dict:
    """
    Полная проверка: server-side + опциональный e2e.

    run_e2e=True: запускается раз в E2E_EVERY_N_CYCLES циклов.
    """
    server = db.query(Server).filter(Server.id == conn.server_id).first()
    if not server:
        return {"ok": False, "health_status": "BROKEN", "reason": "server not found"}

    is_cascade = (conn.connection_type == ConnectionType.CASCADE)
    if is_cascade and conn.ru_server_id:
        target = db.query(Server).filter(Server.id == conn.ru_server_id).first()
    else:
        target = server
    if not target:
        return {"ok": False, "health_status": "BROKEN", "reason": "target server not found"}

    try:
        proto_str = "udp" if conn.protocol == Protocol.AMNEZIA_WG else "tcp"

        with SSHClient(target) as ssh:
            base        = _check_service_and_port(ssh, conn.port, proto_str, conn.protocol)
            latency_res = _check_latency(ssh)

            tls_result = None
            if conn.protocol == Protocol.VLESS_REALITY and base["port_listening"]:
                sni = conn.reality_server_name or "www.microsoft.com"
                tls_result = _check_reality_tls(ssh, target.ip, conn.port, sni)

        # E2E validation
        e2e_result = None
        if run_e2e:
            try:
                from app.services.client_validation_service import validate_connection_e2e
                e2e_result = validate_connection_e2e(db, conn)
                logger.info(
                    f"[e2e] conn {conn.id}: "
                    f"tunnel={e2e_result.get('tunnel_ok')} "
                    f"routing={e2e_result.get('routing_ok')} "
                    f"ip={e2e_result.get('tunnel_ip')}"
                )
            except Exception as e2e_err:
                logger.error(f"[e2e] conn {conn.id} error: {e2e_err}")
                e2e_result = {
                    "tunnel_ok":  None,
                    "routing_ok": None,
                    "validation_errors": [str(e2e_err)[:200]],
                }

        health_status = _classify_health(
            base, tls_result, latency_res, conn.protocol, e2e_result
        )

        result = {
            "ok":             health_status != "BROKEN",
            "health_status":  health_status,
            # Server-side metrics
            "xray_active":    base["xray_active"],
            "port_listening": base["port_listening"],
            "outbound_ok":    base["outbound_ok"],
            "outbound_ip":    base["outbound_ip"],
            "outbound_geo":   base["outbound_geo"],
            "warp_active":    base["warp_active"],
            "latency_ms":     latency_res.get("latency_ms"),
            "jitter_ms":      latency_res.get("jitter_ms"),
            "packet_loss_pct": latency_res.get("packet_loss_pct"),
            "tls_status":     tls_result["tls_status"] if tls_result else None,
            "tls_detail":     tls_result["tls_detail"] if tls_result else None,
            "errors":         base["errors"],
            "server_ip":      target.ip,
        }

        # E2E результаты
        if e2e_result is not None:
            result["tunnel_ok"]          = e2e_result.get("tunnel_ok")
            result["dns_ok"]             = e2e_result.get("dns_ok")
            result["routing_ok"]         = e2e_result.get("routing_ok")
            result["traffic_ok"]         = e2e_result.get("traffic_ok")
            result["internet_ok"]        = e2e_result.get("internet_ok")
            result["tunnel_ip"]          = e2e_result.get("tunnel_ip")
            result["tunnel_geo"]         = e2e_result.get("tunnel_geo")
            result["tunnel_latency_ms"]  = e2e_result.get("tunnel_latency_ms")
            result["validation_errors"]  = e2e_result.get("validation_errors", [])
            result["client_validated_at"] = e2e_result.get("validated_at")
            # ── Новые поля из DB (накопленное состояние) ──────────────────────
            result["tunnel_ip_cached"]    = getattr(conn, "tunnel_ip",         None)
            result["tunnel_geo_cached"]   = getattr(conn, "tunnel_geo",        None)
            result["routing_detail"]      = getattr(conn, "routing_detail",    None)
        else:
            # Берём из ранее сохранённых данных БД (кэшированное состояние)
            result["tunnel_ok"]          = getattr(conn, "tunnel_ok",         None)
            result["routing_ok"]         = getattr(conn, "routing_ok",        None)
            result["dns_ok"]             = getattr(conn, "dns_ok",            None)
            result["traffic_ok"]         = getattr(conn, "traffic_ok",        None)
            result["internet_ok"]        = getattr(conn, "internet_ok",       None)
            result["tunnel_ip"]          = getattr(conn, "tunnel_ip",         None)
            result["tunnel_geo"]         = getattr(conn, "tunnel_geo",        None)
            result["tunnel_latency_ms"]  = getattr(conn, "tunnel_latency_ms", None)
            result["routing_detail"]     = getattr(conn, "routing_detail",    None)
            result["client_validated_at"] = getattr(conn, "client_validated_at", None)
            result["last_validation_error"] = getattr(conn, "last_validation_error", None)
            result["warp_active"]        = base["warp_active"]

        return result

    except Exception as e:
        logger.warning(f"Health check SSH error for conn {conn.id}: {e}")
        return {
            "ok":            False,
            "health_status": "BROKEN",
            "reason":        str(e),
            "errors":        [str(e)],
            "xray_active":   False,
            "port_listening": False,
        }


# ─── Запись в БД ─────────────────────────────────────────────────────────────

def _update_connection_health(db: Session, conn: Connection, health: dict) -> None:
    """Обновляет все health+e2e поля Connection."""
    global _failure_counts
    try:
        now      = datetime.now(timezone.utc)
        ts       = now.strftime("%H:%M:%S")
        h_status = health.get("health_status", "BROKEN")

        # ── Server-side fields ────────────────────────────────────────────────
        def _set(field, value):
            if hasattr(conn, field) and value is not None:
                setattr(conn, field, value)

        _set("health_status",    h_status)
        _set("last_check_at",    now)
        _set("last_check_ok",    (h_status != "BROKEN"))
        _set("xray_active",      health.get("xray_active"))
        _set("port_listening",   health.get("port_listening"))
        _set("warp_active",      health.get("warp_active"))

        if health.get("outbound_ip"):
            _set("last_outbound_ip",  health["outbound_ip"])
        if health.get("outbound_geo"):
            _set("last_outbound_geo", health["outbound_geo"])
        if health.get("tls_status"):
            _set("last_tls_status",   health["tls_status"])
        if health.get("latency_ms") is not None:
            _set("latency_ms",        health["latency_ms"])
        if health.get("jitter_ms") is not None:
            _set("jitter_ms",         health["jitter_ms"])
        if health.get("packet_loss_pct") is not None:
            _set("packet_loss_pct",   health["packet_loss_pct"])
        if h_status != "BROKEN":
            _set("last_active_at",    now)

        # ── E2E fields ────────────────────────────────────────────────────────
        if "tunnel_ok" in health:
            _set("tunnel_ok",    health["tunnel_ok"])
        if "dns_ok" in health:
            _set("dns_ok",       health["dns_ok"])
        if "routing_ok" in health:
            _set("routing_ok",   health["routing_ok"])
        # ── Новые e2e поля (traffic, internet, tunnel IP/geo/latency) ─────────
        if "traffic_ok" in health:
            if hasattr(conn, "traffic_ok"):
                conn.traffic_ok = health["traffic_ok"]
        if "internet_ok" in health:
            if hasattr(conn, "internet_ok"):
                conn.internet_ok = health["internet_ok"]
        if health.get("tunnel_ip") and hasattr(conn, "tunnel_ip"):
            conn.tunnel_ip = health["tunnel_ip"]
        if health.get("tunnel_geo") and hasattr(conn, "tunnel_geo"):
            conn.tunnel_geo = health["tunnel_geo"]
        if health.get("tunnel_latency_ms") is not None and hasattr(conn, "tunnel_latency_ms"):
            conn.tunnel_latency_ms = health["tunnel_latency_ms"]
        # ── routing_detail: SHORT-CIRCUIT объяснение ──────────────────────────
        if hasattr(conn, "routing_detail"):
            routing_ok = health.get("routing_ok")
            tunnel_ip  = health.get("tunnel_ip")
            server_ip  = health.get("server_ip")
            val_errs   = health.get("validation_errors") or []
            if routing_ok is False:
                detail_parts = []
                if tunnel_ip and server_ip:
                    detail_parts.append(f"tunnel_ip={tunnel_ip} == server_ip={server_ip}")
                sc_errs = [e for e in val_errs if "short-circuit" in e.lower() or "routing" in e.lower() or "bypass" in e.lower()]
                if sc_errs:
                    detail_parts.extend(sc_errs[:2])
                conn.routing_detail = "; ".join(detail_parts)[:500] if detail_parts else "traffic bypass detected"
            elif routing_ok is True:
                if tunnel_ip:
                    conn.routing_detail = f"OK: exit={tunnel_ip}" + (f" ({health.get('tunnel_geo','')}" + ")" if health.get("tunnel_geo") else "")
                else:
                    conn.routing_detail = "OK"
            elif routing_ok is None and val_errs:
                conn.routing_detail = "not_collected: " + "; ".join(val_errs[:2])[:200]
        if "client_validated_at" in health and health["client_validated_at"]:
            _set("client_validated_at", health["client_validated_at"])
        if "validation_errors" in health:
            errs = health["validation_errors"] or []
            if hasattr(conn, "last_validation_error"):
                conn.last_validation_error = "; ".join(errs)[:500] if errs else None

        # ── Tunnel IP/geo (приоритет у e2e, иначе server-side) ───────────────
        if health.get("tunnel_ip"):
            _set("last_outbound_ip",  health["tunnel_ip"])
        if health.get("tunnel_geo"):
            _set("last_outbound_geo", health["tunnel_geo"])

        # ── Лог ──────────────────────────────────────────────────────────────
        lat   = health.get("latency_ms")
        loss  = health.get("packet_loss_pct")
        tun   = health.get("tunnel_ok")
        tls_p = f",tls={health['tls_status']}" if health.get("tls_status") else ""
        net_p = f",net={health.get('outbound_ip') or 'no'}"
        lat_p = f",lat={lat}ms" if lat is not None else ""
        tun_p = f",tun={'ok' if tun else ('fail' if tun is False else '?')}" if tun is not None else ""

        if h_status == "HEALTHY":
            note = f"[HC:{ts}:HEALTHY:xray=ok,port=ok{tls_p}{net_p}{lat_p}{tun_p}]"
        elif h_status == "DEGRADED":
            issues = " ".join((health.get("errors") or []) +
                               (health.get("validation_errors") or []))[:60]
            note = f"[HC:{ts}:DEGRADED:{issues}{tls_p}{lat_p}{tun_p}]"
        else:
            issues = " ".join((health.get("errors") or [health.get("reason", "?")]))[:80]
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
            logger.warning(
                f"conn {cid} BROKEN (count={cnt}/{MAX_FAILURES_BEFORE_BROKEN})"
            )
            if cnt >= MAX_FAILURES_BEFORE_BROKEN:
                if conn.status == ConnectionStatus.ACTIVE:
                    conn.status = ConnectionStatus.ERROR
                db.commit()
                try:
                    from app.services import auto_recovery_service
                    recovery_result = auto_recovery_service.attempt_recovery(
                        db, conn, health
                    )
                    if recovery_result.get("recovered"):
                        _failure_counts[cid] = 0
                        logger.info(f"conn {cid} auto-recovered")
                    else:
                        logger.warning(
                            f"conn {cid} auto-recovery failed: "
                            f"{recovery_result.get('reason')}"
                        )
                except Exception as rec_err:
                    logger.error(
                        f"auto_recovery_service error for conn {cid}: {rec_err}"
                    )
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
    global _cycle_counter
    _cycle_counter += 1
    run_e2e = (_cycle_counter % E2E_EVERY_N_CYCLES == 0)

    db = SessionLocal()
    try:
        connections = db.query(Connection).filter(
            Connection.is_active    == True,
            Connection.setup_status == "done",
        ).all()
        logger.info(
            f"Health check cycle v4 #{_cycle_counter}: "
            f"{len(connections)} connections, e2e={'YES' if run_e2e else 'no'}"
        )
        for conn in connections:
            if _stop_event.is_set():
                break
            try:
                health = check_connection_health(db, conn, run_e2e=run_e2e)
                _update_connection_health(db, conn, health)
                logger.debug(
                    f"  [{health['health_status']}] conn {conn.id} "
                    f"({conn.protocol}/{conn.connection_type}) "
                    f"lat={health.get('latency_ms')}ms "
                    f"tunnel={health.get('tunnel_ok')} "
                    f"tls={health.get('tls_status')}"
                )
            except Exception as e:
                logger.error(f"Health check error conn {conn.id}: {e}")
            time.sleep(2)
    except Exception as e:
        logger.error(f"Health check cycle error: {e}")
    finally:
        db.close()


def _health_check_worker() -> None:
    logger.info(f"Health check worker v4 started (interval={HEALTH_CHECK_INTERVAL}s)")
    _stop_event.wait(timeout=60)
    while not _stop_event.is_set():
        try:
            run_health_check_cycle()
        except Exception as e:
            logger.error(f"Health check worker error: {e}")
        _stop_event.wait(timeout=HEALTH_CHECK_INTERVAL)
    logger.info("Health check worker v4 stopped")


# ─── Lifecycle ───────────────────────────────────────────────────────────────

def start_health_check_worker() -> None:
    global _health_thread
    if _health_thread and _health_thread.is_alive():
        logger.warning("Health check worker already running")
        return
    _stop_event.clear()
    _health_thread = threading.Thread(
        target=_health_check_worker,
        name="health-check-worker-v4",
        daemon=True,
    )
    _health_thread.start()
    logger.info("Health check worker v4 thread started")


def stop_health_check_worker() -> None:
    global _health_thread
    _stop_event.set()
    if _health_thread:
        _health_thread.join(timeout=10)
        _health_thread = None
    logger.info("Health check worker v4 stopped")


def get_connection_health_status(db: Session, connection_id: int) -> dict:
    """
    On-demand проверка одного подключения (API endpoint /health).
    Всегда запускает e2e для актуального результата.
    """
    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if not conn:
        return {"ok": False, "health_status": "BROKEN", "reason": "not found"}
    health = check_connection_health(db, conn, run_e2e=True)
    _update_connection_health(db, conn, health)
    return health
