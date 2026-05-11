"""
Auto-Recovery Service — автоматическое восстановление VPN подключений.

Триггеры восстановления (по убыванию агрессивности):
  1. xray stopped         → systemctl restart xray
  2. port not listening   → systemctl restart xray + ufw/iptables reopen
  3. outbound unavailable → restart xray (может помочь если routing сломан)
  4. TLS handshake failed → проверяем конфиг, при необходимости redeploy

Anti-flap защита:
  MAX_RECOVERIES_PER_24H = 3  — не более 3 auto-recovery за 24 часа
  RECOVERY_COOLDOWN_MINUTES = 10 — минимум 10 минут между попытками
"""
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.connection import Connection, Protocol, ConnectionStatus
from app.models.server import Server
from app.services.ssh_service import SSHClient

logger = logging.getLogger(__name__)

MAX_RECOVERIES_PER_24H    = 3
RECOVERY_COOLDOWN_MINUTES = 10


def _can_recover(conn: Connection) -> Tuple[bool, str]:
    """Проверяет anti-flap условия перед восстановлением."""
    now = datetime.now(timezone.utc)

    # Cooldown между попытками
    if conn.last_recovery_at:
        last = conn.last_recovery_at
        if not last.tzinfo:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds() / 60
        if elapsed < RECOVERY_COOLDOWN_MINUTES:
            return False, f"cooldown: {int(RECOVERY_COOLDOWN_MINUTES - elapsed)}m remaining"

    # Лимит за 24ч
    count = conn.recovery_count_24h or 0
    if count >= MAX_RECOVERIES_PER_24H:
        return False, f"limit reached: {count}/{MAX_RECOVERIES_PER_24H} recoveries in 24h"

    return True, "ok"


def _append_recovery_log(conn: Connection, line: str):
    """Добавляет строку в recovery_log (хранит последние 20 строк)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {line}"
    existing = (conn.recovery_log or "").splitlines()
    # Ротация: храним последние 20 строк
    existing = existing[-19:] + [entry]
    conn.recovery_log = "\n".join(existing)


def _restart_xray(ssh) -> Tuple[bool, str]:
    """Перезапускает xray.service и проверяет результат."""
    code, out, err = ssh.exec("systemctl restart xray 2>&1", timeout=15)
    if code != 0:
        return False, f"restart failed: {(err or out or '').strip()[:80]}"
    # Ждём 3 секунды и проверяем статус
    import time
    time.sleep(3)
    _, st_out, _ = ssh.exec("systemctl is-active xray 2>/dev/null", timeout=10)
    active = st_out.strip() == "active"
    return active, "active" if active else "still not active after restart"


def _reopen_port(ssh, port: int, proto: str = "tcp") -> Tuple[bool, str]:
    """Переоткрывает порт через ufw или iptables."""
    ufw_proto = "any" if proto == "udp" else proto
    ipt_proto = proto

    cmd = (
        f"if ufw status 2>/dev/null | grep -q 'Status: active'; then "
        f"  ufw allow {port}/{ufw_proto} 2>&1; "
        f"elif command -v iptables >/dev/null 2>&1; then "
        f"  iptables -C INPUT -p {ipt_proto} --dport {port} -j ACCEPT 2>/dev/null || "
        f"  iptables -I INPUT -p {ipt_proto} --dport {port} -j ACCEPT 2>&1; "
        f"else echo 'no_firewall_tool'; fi"
    )
    code, out, err = ssh.exec(cmd, timeout=15)
    result = (out or "").strip()
    if "no_firewall_tool" in result:
        return True, "no firewall tool (ok, port likely open)"
    return code == 0, result[:80] if result else "port reopen attempted"


def _validate_xray_config(ssh, conn_id: int) -> Tuple[bool, str]:
    """Проверяет текущий конфиг xray через xray -test."""
    code, out, err = ssh.exec(
        "xray -test -config /usr/local/etc/xray/config.json 2>&1 | head -5",
        timeout=20
    )
    out_combined = (out or "") + (err or "")
    if code != 0 or "error" in out_combined.lower():
        return False, out_combined.strip()[:120]
    return True, "config OK"


def attempt_recovery(
    db: Session,
    conn: Connection,
    health: dict,
) -> dict:
    """
    Пытается восстановить подключение на основе результатов health-check.

    health dict: {health_status, xray_active, port_listening, outbound_ok, tls_status, errors}

    Возвращает:
      {
        attempted:  bool,   # была ли попытка
        success:    bool,   # успех
        actions:    list,   # что было сделано
        reason:     str,    # почему не пытались (если attempted=False)
      }
    """
    result = {"attempted": False, "success": False, "actions": [], "reason": ""}

    # Не восстанавливаем если HEALTHY или DEGRADED без критических проблем
    h_status = health.get("health_status", "BROKEN")
    xray_ok  = health.get("xray_active", True)
    port_ok  = health.get("port_listening", True)
    out_ok   = health.get("outbound_ok", True)

    # Восстановление только при BROKEN
    if h_status != "BROKEN":
        result["reason"] = f"health_status={h_status}, no recovery needed"
        return result

    # Anti-flap check
    can, reason = _can_recover(conn)
    if not can:
        result["reason"] = reason
        _append_recovery_log(conn, f"⏸ Recovery skipped: {reason}")
        db.commit()
        return result

    result["attempted"] = True
    actions = []

    # Определяем сервер для SSH
    from app.models.connection import ConnectionType
    from app.db.database import SessionLocal

    is_cascade = conn.connection_type == ConnectionType.CASCADE
    use_ru = (
        is_cascade
        and conn.ru_server_id
        and conn.protocol in (Protocol.VLESS_REALITY,)
    )
    target_server = (
        db.query(Server).filter(Server.id == conn.ru_server_id).first()
        if use_ru
        else db.query(Server).filter(Server.id == conn.server_id).first()
    )

    if not target_server:
        result["reason"] = "target server not found"
        return result

    now = datetime.now(timezone.utc)
    _append_recovery_log(conn, f"🔄 Starting recovery: xray={xray_ok} port={port_ok} outbound={out_ok}")
    conn.recovery_status = "recovering"
    conn.last_recovery_at = now
    conn.recovery_count_24h = (conn.recovery_count_24h or 0) + 1
    db.commit()

    try:
        with SSHClient(target_server) as ssh:
            # ── Шаг 1: Validate config ────────────────────────────────────────
            cfg_ok, cfg_msg = _validate_xray_config(ssh, conn.id)
            actions.append(f"config_check: {cfg_ok} ({cfg_msg[:60]})")
            _append_recovery_log(conn, f"  [1] Config check: {'OK' if cfg_ok else 'FAIL'} — {cfg_msg[:60]}")

            if not cfg_ok:
                # Конфиг сломан → redeploy
                _append_recovery_log(conn, "  [1→] Config broken → triggering redeploy")
                actions.append("redeploy: config broken")
                result["success"] = _trigger_redeploy(db, conn)
                if result["success"]:
                    conn.recovery_status = "recovered"
                    _append_recovery_log(conn, "✅ Recovered via redeploy")
                else:
                    conn.recovery_status = "failed"
                    _append_recovery_log(conn, "❌ Redeploy failed")
                conn.last_recovery_at = now
                db.commit()
                result["actions"] = actions
                return result

            # ── Шаг 2: Restart xray если не работает ─────────────────────────
            if not xray_ok:
                ok, msg = _restart_xray(ssh)
                actions.append(f"restart_xray: {ok} ({msg})")
                _append_recovery_log(conn, f"  [2] Restart xray: {'OK' if ok else 'FAIL'} — {msg}")

            # ── Шаг 3: Reopen port если не слушается ─────────────────────────
            if not port_ok:
                proto_str = "udp" if conn.protocol == Protocol.AMNEZIA_WG else "tcp"
                ok, msg = _reopen_port(ssh, conn.port, proto_str)
                actions.append(f"reopen_port_{conn.port}: {ok} ({msg})")
                _append_recovery_log(conn, f"  [3] Reopen port {conn.port}: {'OK' if ok else 'FAIL'} — {msg}")

                # После открытия порта — ещё раз рестартуем xray
                ok2, msg2 = _restart_xray(ssh)
                actions.append(f"restart_xray_after_port: {ok2} ({msg2})")
                _append_recovery_log(conn, f"  [3→] Restart xray: {'OK' if ok2 else 'FAIL'} — {msg2}")

            # ── Шаг 4: Verify recovery ────────────────────────────────────────
            import time
            time.sleep(3)

            _, xray_st, _ = ssh.exec("systemctl is-active xray 2>/dev/null", timeout=10)
            xray_active_now = xray_st.strip() == "active"

            flag = "" if conn.protocol != Protocol.AMNEZIA_WG else "u"
            _, ss_out, _ = ssh.exec(
                f"ss -t{flag}lnp 2>/dev/null | grep ':{conn.port}' || echo NOT_LISTENING",
                timeout=10
            )
            port_active_now = str(conn.port) in ss_out and "NOT_LISTENING" not in ss_out

            actions.append(f"verify: xray={xray_active_now} port={port_active_now}")
            _append_recovery_log(conn, f"  [4] Verify: xray={xray_active_now} port={port_active_now}")

            if xray_active_now and port_active_now:
                result["success"] = True
                conn.recovery_status = "recovered"
                conn.status = ConnectionStatus.ACTIVE
                _append_recovery_log(conn, "✅ Recovery successful")
            else:
                # Финальная попытка — полный redeploy
                _append_recovery_log(conn, "  [4→] Basic recovery failed → triggering redeploy")
                actions.append("redeploy: basic recovery failed")
                ok_deploy = _trigger_redeploy(db, conn)
                result["success"] = ok_deploy
                conn.recovery_status = "recovered" if ok_deploy else "failed"
                _append_recovery_log(conn, f"{'✅' if ok_deploy else '❌'} Redeploy {'ok' if ok_deploy else 'failed'}")

    except Exception as e:
        logger.error(f"Recovery error for conn {conn.id}: {e}")
        actions.append(f"ssh_error: {str(e)[:80]}")
        _append_recovery_log(conn, f"❌ Recovery exception: {str(e)[:80]}")
        conn.recovery_status = "failed"

    conn.last_recovery_at = now
    db.commit()
    result["actions"] = actions
    return result


def _trigger_redeploy(db: Session, conn: Connection) -> bool:
    """Запускает полный redeploy подключения (синхронно, в текущем потоке)."""
    try:
        from app.services import deploy_service
        eu_server = db.query(Server).filter(Server.id == conn.server_id).first()
        ru_server = db.query(Server).filter(Server.id == conn.ru_server_id).first() if conn.ru_server_id else None

        from app.models.connection import Protocol as P, ConnectionType as CT

        if conn.protocol == P.VLESS_REALITY:
            ok, msg = deploy_service.deploy_vless_reality_connection(
                db, conn, eu_server,
                exit_server=ru_server,
                is_cascade=(conn.connection_type == CT.CASCADE),
            )
        elif conn.protocol == P.AMNEZIA_WG:
            ok, msg = deploy_service.deploy_amnezia_wg_connection(
                db, conn, eu_server,
                ru_server=ru_server,
                is_cascade=(conn.connection_type == CT.CASCADE),
            )
        elif conn.protocol == P.NAIVE_PROXY:
            ok, msg = deploy_service.deploy_naiveproxy_connection(
                db, conn, eu_server,
                ru_server=ru_server,
                is_cascade=(conn.connection_type == CT.CASCADE),
            )
        else:
            return False

        db.commit()
        return ok
    except Exception as e:
        logger.error(f"_trigger_redeploy error conn {conn.id}: {e}")
        return False


def reset_recovery_counters_if_needed(db: Session, conn: Connection):
    """
    Сбрасывает счётчик recovery_count_24h если прошло >24ч с последнего рекавери.
    Вызывается в начале каждого health-check цикла.
    """
    if not conn.last_recovery_at:
        return
    now = datetime.now(timezone.utc)
    last = conn.last_recovery_at
    if not last.tzinfo:
        last = last.replace(tzinfo=timezone.utc)
    if (now - last).total_seconds() > 86400:
        conn.recovery_count_24h = 0
        db.commit()
