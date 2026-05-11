"""
Connection management service — новый флоу.
Создаёт все подключения сразу (direct и/или cascade) с логированием в setup_log.
"""
import json
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Dict
from sqlalchemy.orm import Session

from app.models.connection import Connection, Protocol, ConnectionType, ConnectionStatus
from app.models.server import Server, ServerRole, ServerStatus
from app.services.port_service import assign_free_port
from app.services.config_generator import generate_uuid, generate_password, generate_short_id
from app.services import deploy_service

logger = logging.getLogger(__name__)

PROTOCOLS_ALL = [Protocol.VLESS_REALITY, Protocol.AMNEZIA_WG, Protocol.NAIVE_PROXY]


# ─── helpers ────────────────────────────────────────────────────────────────

def _log(db: Session, conn: Connection, line: str):
    """Append one log line to connection.setup_log."""
    existing = conn.setup_log or ""
    conn.setup_log = existing + line + "\n"
    db.commit()


def _set_step(db: Session, conn: Connection, step: str):
    conn.setup_step = step
    db.commit()


def _set_status(db: Session, conn: Connection, status: str, error: str = None):
    conn.setup_status = status
    if error:
        conn.setup_error = error
    db.commit()


def get_connection(db: Session, connection_id: int) -> Optional[Connection]:
    return db.query(Connection).filter(Connection.id == connection_id).first()


def get_connections(db: Session, skip: int = 0, limit: int = 200) -> List[Connection]:
    return db.query(Connection).offset(skip).limit(limit).all()


def get_server_connections(db: Session, server_id: int) -> List[Connection]:
    return db.query(Connection).filter(Connection.server_id == server_id).all()


def delete_connection(db: Session, conn: Connection):
    server = db.query(Server).filter(Server.id == conn.server_id).first()
    if server and server.status == ServerStatus.ONLINE:
        try:
            deploy_service.delete_connection_from_server(db, conn, server)
        except Exception as e:
            logger.warning(f"Could not remove from server: {e}")
    db.delete(conn)
    db.commit()


def toggle_connection(db: Session, conn: Connection, active: bool) -> Connection:
    conn.is_active = active
    conn.status = ConnectionStatus.ACTIVE if active else ConnectionStatus.INACTIVE
    db.commit()
    db.refresh(conn)
    return conn


# ─── grouped list для UI ────────────────────────────────────────────────────

def get_connections_grouped(db: Session) -> list:
    """
    Возвращает подключения, сгруппированные по EU серверу,
    внутри — по типу direct/cascade.
    """
    eu_servers = db.query(Server).filter(
        Server.role == ServerRole.EU,
        Server.is_active == True
    ).all()

    result = []
    for eu_srv in eu_servers:
        direct_conns = db.query(Connection).filter(
            Connection.server_id == eu_srv.id,
            Connection.connection_type == ConnectionType.DIRECT,
        ).order_by(Connection.protocol).all()

        cascade_conns = db.query(Connection).filter(
            Connection.server_id == eu_srv.id,
            Connection.connection_type == ConnectionType.CASCADE,
        ).order_by(Connection.protocol).all()

        if not direct_conns and not cascade_conns:
            continue

        result.append({
            "eu_server": {
                "id":      eu_srv.id,
                "name":    eu_srv.name,
                "ip":      eu_srv.ip,
                "country": eu_srv.country,
                "status":  eu_srv.status,
            },
            "direct":  [_conn_row(db, c) for c in direct_conns],
            "cascade": [_conn_row(db, c) for c in cascade_conns],
        })
    return result


def _conn_row(db: Session, c: Connection) -> dict:
    ru_srv = None
    if c.ru_server_id:
        ru_srv = db.query(Server).filter(Server.id == c.ru_server_id).first()

    # Основной сервер подключения
    eu_srv = db.query(Server).filter(Server.id == c.server_id).first()

    # Человекочитаемое название для VPN-клиентов
    # Формат: "{flag} {display_name} | {PROTOCOL} ({type})"
    # Пример: "🇫🇮 FIN 1 | VLESS (direct)"
    _flag    = (eu_srv.flag_emoji   if eu_srv else '') or ''
    _dname   = (eu_srv.display_name if eu_srv else '') or (eu_srv.name if eu_srv else '')
    _proto   = {
        'vless_reality': 'VLESS',
        'amnezia_wg':    'AWG',
        'naive_proxy':   'NaiveProxy',
    }.get(str(c.protocol), str(c.protocol))
    _ctype   = str(c.connection_type)  # 'direct' / 'cascade'
    parts    = [p for p in [_flag, _dname] if p]
    client_name = (' '.join(parts) + f' | {_proto} ({_ctype})') if parts else f'{_proto} ({_ctype})'

    return {
        "id":              c.id,
        "protocol":        c.protocol,
        "connection_type": c.connection_type,
        "status":          c.status,
        "is_active":       c.is_active,
        "client_link":     c.client_link,
        "config_text":     c.config_text,
        "config_qr":       c.config_qr,
        "split_tunnel_enabled": c.split_tunnel_enabled,
        "warp_enabled": getattr(c, "warp_enabled", False),
        "setup_status":    c.setup_status,
        "setup_step":      c.setup_step,
        "setup_error":     c.setup_error,
        "created_at":      c.created_at.isoformat() if c.created_at else None,
        # Название подключения для VPN-клиентов
        "client_name":     client_name,
        # Основной (EU/exit) сервер
        "server": {
            "id":           eu_srv.id,
            "name":         eu_srv.name,
            "ip":           eu_srv.ip,
            "country":      eu_srv.country,
            "flag_emoji":   eu_srv.flag_emoji   or '',
            "display_name": eu_srv.display_name or eu_srv.name,
        } if eu_srv else None,
        "ru_server": {
            "id":           ru_srv.id,
            "name":         ru_srv.name,
            "ip":           ru_srv.ip,
            "country":      ru_srv.country,
            "flag_emoji":   ru_srv.flag_emoji   or '',
            "display_name": ru_srv.display_name or ru_srv.name,
        } if ru_srv else None,
        # VLESS
        "uuid":               c.uuid,
        "reality_public_key": c.reality_public_key,
        "reality_short_id":   c.reality_short_id,
        "reality_server_name":c.reality_server_name,
        "reality_fingerprint":c.reality_fingerprint,
        "port":               c.port,
        # AWG
        "wg_public_key":          c.wg_public_key,
        "wg_client_private_key":  c.wg_client_private_key,
        "wg_client_public_key":   c.wg_client_public_key,
        "wg_preshared_key":       c.wg_preshared_key,
        "wg_client_ip":           c.wg_client_ip,
        "awg_junk_packet_count":  c.awg_junk_packet_count,
        "awg_junk_packet_min_size": c.awg_junk_packet_min_size,
        "awg_junk_packet_max_size": c.awg_junk_packet_max_size,
        "awg_s1": c.awg_s1, "awg_s2": c.awg_s2,
        "awg_h1": c.awg_h1, "awg_h2": c.awg_h2,
        "awg_h3": c.awg_h3, "awg_h4": c.awg_h4,
        # NaiveProxy
        "password":  c.password,
        "np_domain": c.np_domain,
        "np_user":   c.np_user,
        # Health monitoring (v3)
        "health_status":      getattr(c, 'health_status',      None),
        "last_check_at":      getattr(c, 'last_check_at',      None).isoformat() if getattr(c, 'last_check_at', None) else None,
        "last_check_ok":      getattr(c, 'last_check_ok',      None),
        "last_outbound_ip":   getattr(c, 'last_outbound_ip',   None),
        "last_outbound_geo":  getattr(c, 'last_outbound_geo',  None),
        "last_tls_status":    getattr(c, 'last_tls_status',    None),
        "latency_ms":         getattr(c, 'latency_ms',         None),
        "jitter_ms":          getattr(c, 'jitter_ms',          None),
        "packet_loss_pct":    getattr(c, 'packet_loss_pct',    None),
        # Auto-recovery
        "recovery_status":    getattr(c, 'recovery_status',    None),
        "last_recovery_at":   getattr(c, 'last_recovery_at',   None).isoformat() if getattr(c, 'last_recovery_at', None) else None,
        "recovery_log":       getattr(c, 'recovery_log',       None),
        "recovery_count_24h": getattr(c, 'recovery_count_24h', 0),
        # Uptime
        "last_active_at":     getattr(c, 'last_active_at',    None).isoformat() if getattr(c, 'last_active_at', None) else None,
        "total_uptime_seconds": getattr(c, 'total_uptime_seconds', 0),
    }


# ─── wizard entry point ─────────────────────────────────────────────────────

def create_connections_batch(
    db: Session,
    eu_server_id: int,
    ru_server_id: Optional[int],
    create_direct: bool,
    create_cascade: bool,
    protocols: Optional[List[str]] = None,
) -> List[int]:
    """
    Создаёт записи Connection — ровно по ОДНОЙ на каждый протокол × тип.

    Итого:
      - только direct (без RU):       3 подключения (VLESS, AWG, NaiveProxy)
      - только cascade (с RU):        3 подключения
      - direct + cascade (с RU):      6 подключений

    Дубли (2 порта на один протокол) недопустимы.
    Перед созданием проверяем, не существует ли уже подключение
    с тем же eu_server_id + protocol + connection_type — если есть, пропускаем.
    """
    eu_server = db.query(Server).filter(Server.id == eu_server_id).first()
    if not eu_server:
        raise ValueError("EU server not found")

    ru_server = None
    if create_cascade:
        if not ru_server_id:
            raise ValueError("RU server required for cascade")
        ru_server = db.query(Server).filter(Server.id == ru_server_id).first()
        if not ru_server:
            raise ValueError("RU server not found")

    # Фильтрация протоколов: None = все три, иначе только выбранные
    _PROTO_MAP = {
        "vless_reality": Protocol.VLESS_REALITY,
        "amnezia_wg":    Protocol.AMNEZIA_WG,
        "naive_proxy":   Protocol.NAIVE_PROXY,
    }
    if protocols:
        filtered_protocols = [_PROTO_MAP[p] for p in protocols if p in _PROTO_MAP]
        if not filtered_protocols:
            raise ValueError("Не выбран ни один корректный протокол")
    else:
        filtered_protocols = PROTOCOLS_ALL

    created_ids = []

    def _already_exists(proto: Protocol, ctype: ConnectionType) -> bool:
        """True if an active connection with same EU server + protocol + type exists."""
        existing = db.query(Connection).filter(
            Connection.server_id       == eu_server_id,
            Connection.protocol        == proto,
            Connection.connection_type == ctype,
            Connection.is_active       == True,
        ).first()
        return existing is not None

    def _make(proto: Protocol, ctype: ConnectionType, eu_srv: Server, ru_srv: Optional[Server]):
        ctype_str = ctype.value if hasattr(ctype, 'value') else str(ctype)
        is_cascade = (ctype == ConnectionType.CASCADE)

        # ── PORT ASSIGNMENT ────────────────────────────────────────────────────
        # CASCADE: the VPN port is listened on the RU server, not EU.
        # So uniqueness MUST be enforced against ru_server_id, not eu server_id.
        # DIRECT:  port is on EU server — check against EU server_id.
        if is_cascade and ru_srv:
            port = assign_free_port(
                db,
                server_id=eu_srv.id,        # EU server id (for logging)
                protocol=proto,
                connection_type=ctype_str,
                ru_server_id=ru_srv.id,     # RU server id (actual uniqueness check)
            )
        else:
            port = assign_free_port(
                db,
                server_id=eu_srv.id,
                protocol=proto,
                connection_type=ctype_str,
            )

        conn = Connection(
            server_id            = eu_srv.id,
            ru_server_id         = ru_srv.id if ru_srv else None,
            connection_type      = ctype,
            protocol             = proto,
            port                 = port,
            status               = ConnectionStatus.DEPLOYING,
            setup_status         = "pending",
            setup_log            = "",
            split_tunnel_enabled = True,
            warp_enabled         = True,
        )

        # ── PROTOCOL DEFAULTS ──────────────────────────────────────────────────
        if proto == Protocol.VLESS_REALITY:
            conn.uuid                = generate_uuid()
            conn.reality_server_name = "www.microsoft.com"
            conn.reality_fingerprint = "chrome"

        elif proto == Protocol.AMNEZIA_WG:
            conn.awg_junk_packet_count    = 4
            conn.awg_junk_packet_min_size = 40
            conn.awg_junk_packet_max_size = 70
            conn.awg_s1 = 50;  conn.awg_s2 = 100
            conn.awg_h1 = 1;   conn.awg_h2 = 2
            conn.awg_h3 = 3;   conn.awg_h4 = 4

        elif proto == Protocol.NAIVE_PROXY:
            conn.password = generate_password(24)
            conn.np_user  = "vpnuser"
            # ── AUTO np_domain ─────────────────────────────────────────────────
            # NaiveProxy requires a real domain for TLS (HTTPS camouflage).
            # Without a domain Caddy uses "tls internal" → self-signed cert →
            # clients get "TLS alert: internal error" and connection fails.
            #
            # DIRECT:  NaiveProxy runs on EU server → use EU server domain.
            # CASCADE: NaiveProxy listens on RU server → use RU server domain.
            if is_cascade and ru_srv:
                conn.np_domain = ru_srv.domain or None
            else:
                conn.np_domain = eu_srv.domain or None

        db.add(conn)
        db.flush()
        return conn.id

    if create_direct:
        for proto in filtered_protocols:
            if _already_exists(proto, ConnectionType.DIRECT):
                logger.info(f"Skipping duplicate DIRECT {proto} for EU server {eu_server_id}")
                continue
            cid = _make(proto, ConnectionType.DIRECT, eu_server, None)
            created_ids.append(cid)

    if create_cascade and ru_server:
        for proto in filtered_protocols:
            if _already_exists(proto, ConnectionType.CASCADE):
                logger.info(f"Skipping duplicate CASCADE {proto} for EU server {eu_server_id}")
                continue
            cid = _make(proto, ConnectionType.CASCADE, eu_server, ru_server)
            created_ids.append(cid)

    db.commit()

    if not created_ids:
        logger.warning(
            f"create_connections_batch: no new connections created for EU={eu_server_id} "
            f"(all already exist). Returning empty list."
        )
        return []

    # Start background deployment
    t = threading.Thread(
        target=_run_batch_deploy,
        args=(created_ids, eu_server_id, ru_server_id),
        daemon=True
    )
    t.start()

    return created_ids


def _run_batch_deploy(conn_ids: List[int], eu_server_id: int, ru_server_id: Optional[int]):
    """Фоновый деплой — выполняется в отдельном потоке."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        eu_server = db.query(Server).filter(Server.id == eu_server_id).first()
        ru_server = db.query(Server).filter(Server.id == ru_server_id).first() if ru_server_id else None

        for cid in conn_ids:
            conn = db.query(Connection).filter(Connection.id == cid).first()
            if not conn:
                continue
            try:
                _deploy_one(db, conn, eu_server, ru_server)
            except Exception as e:
                logger.error(f"Deploy error conn {cid}: {e}")
                _log(db, conn, f"❌ Критическая ошибка: {e}")
                _set_status(db, conn, "failed", str(e))
                conn.status = ConnectionStatus.ERROR
                db.commit()
    finally:
        db.close()


def _deploy_one(db: Session, conn: Connection, eu_server: Server, ru_server: Optional[Server]):
    """Деплой одного подключения с логированием."""
    _set_status(db, conn, "in_progress")

    proto = conn.protocol
    ctype = conn.connection_type

    _log(db, conn, f"⏳ Начало настройки {proto} ({ctype})")

    try:
        if proto == Protocol.VLESS_REALITY:
            ok, msg = deploy_service.deploy_vless_reality_connection(
                db, conn, eu_server,
                exit_server=ru_server if ctype == ConnectionType.CASCADE else None,
                is_cascade=(ctype == ConnectionType.CASCADE),
            )
        elif proto == Protocol.AMNEZIA_WG:
            ok, msg = deploy_service.deploy_amnezia_wg_connection(
                db, conn, eu_server,
                ru_server=ru_server if ctype == ConnectionType.CASCADE else None,
                is_cascade=(ctype == ConnectionType.CASCADE),
            )
        elif proto == Protocol.NAIVE_PROXY:
            ok, msg = deploy_service.deploy_naiveproxy_connection(
                db, conn, eu_server,
                ru_server=ru_server if ctype == ConnectionType.CASCADE else None,
                is_cascade=(ctype == ConnectionType.CASCADE),
            )
        else:
            ok, msg = False, f"Неизвестный протокол: {proto}"

        if ok:
            _log(db, conn, f"✅ {msg}")
            conn.status = ConnectionStatus.ACTIVE
            _set_status(db, conn, "done")
        else:
            _log(db, conn, f"❌ {msg}")
            conn.status = ConnectionStatus.ERROR
            _set_status(db, conn, "failed", msg)

        db.commit()

    except Exception as e:
        _log(db, conn, f"❌ Исключение: {e}")
        conn.status = ConnectionStatus.ERROR
        _set_status(db, conn, "failed", str(e))
        db.commit()
        raise


# ─── patch params ───────────────────────────────────────────────────────────

def patch_connection_param(db: Session, conn: Connection, field: str, value) -> Tuple[bool, str]:
    """Обновить один параметр и переприменить конфиг на сервере."""
    allowed = {
        "reality_server_name", "reality_fingerprint", "port",
        "awg_junk_packet_count", "awg_junk_packet_min_size", "awg_junk_packet_max_size",
        "awg_s1", "awg_s2", "awg_h1", "awg_h2", "awg_h3", "awg_h4",
        "np_domain", "np_user", "split_tunnel_enabled", "warp_enabled",
    }
    if field not in allowed:
        return False, f"Поле '{field}' недоступно для изменения"

    setattr(conn, field, value)
    db.commit()

    # переприменяем конфиг
    eu_server = db.query(Server).filter(Server.id == conn.server_id).first()
    ru_server = db.query(Server).filter(Server.id == conn.ru_server_id).first() if conn.ru_server_id else None

    try:
        if conn.protocol == Protocol.VLESS_REALITY:
            ok, msg = deploy_service.deploy_vless_reality_connection(
                db, conn, eu_server,
                exit_server=ru_server,
                is_cascade=(conn.connection_type == ConnectionType.CASCADE),
            )
        elif conn.protocol == Protocol.AMNEZIA_WG:
            ok, msg = deploy_service.deploy_amnezia_wg_connection(
                db, conn, eu_server,
                ru_server=ru_server,
                is_cascade=(conn.connection_type == ConnectionType.CASCADE),
            )
        elif conn.protocol == Protocol.NAIVE_PROXY:
            ok, msg = deploy_service.deploy_naiveproxy_connection(
                db, conn, eu_server,
                ru_server=ru_server,
                is_cascade=(conn.connection_type == ConnectionType.CASCADE),
            )
        else:
            ok, msg = False, "Неизвестный протокол"
        db.commit()
        return ok, msg
    except Exception as e:
        db.commit()
        return False, str(e)


# ─── check status ────────────────────────────────────────────────────────────

def _check_alive_on_server(ssh, conn: Connection) -> bool:
    """Проверяет живость одного подключения через уже открытый SSH.

    Вызывается как для EU-, так и для RU-сервера — в зависимости от того,
    на каком хосте реально слушается порт/сервис.
    """
    if conn.protocol == Protocol.VLESS_REALITY:
        _, out, _ = ssh.exec(f"ss -tlnp 2>/dev/null | grep ':{conn.port} '")
        return str(conn.port) in out
    elif conn.protocol == Protocol.AMNEZIA_WG:
        _, out, _ = ssh.exec("awg show 2>/dev/null || wg show 2>/dev/null")
        return "interface" in out.lower()
    elif conn.protocol == Protocol.NAIVE_PROXY:
        _, out, _ = ssh.exec("systemctl is-active caddy 2>/dev/null")
        return out.strip() == "active"
    return False


def _get_check_server(db: Session, conn: Connection):
    """Возвращает сервер, на котором надо проверять живость подключения.

    Правила:
    - direct: всегда EU сервер (server_id)
    - cascade VLESS+Reality: RU сервер (ru_server_id) — там Xray слушает входящий порт
    - cascade NaiveProxy:    RU сервер (ru_server_id) — там caddy-naive принимает трафик
    - cascade AmneziaWG:     EU сервер (server_id)    — там поднят wg-интерфейс
    """
    is_cascade = conn.connection_type == ConnectionType.CASCADE
    use_ru = (
        is_cascade
        and conn.ru_server_id
        and conn.protocol in (Protocol.VLESS_REALITY, Protocol.NAIVE_PROXY)
    )
    if use_ru:
        return db.query(Server).filter(Server.id == conn.ru_server_id).first()
    return db.query(Server).filter(Server.id == conn.server_id).first()


def check_connection_live(db: Session, conn: Connection) -> Tuple[bool, str]:
    """Проверяет что подключение реально активно на сервере.

    Для cascade VLESS+Reality и cascade NaiveProxy проверяем RU сервер,
    т.к. именно там слушается входящий порт.
    Для остальных (direct любой, cascade AWG) — EU сервер.
    """
    check_server = _get_check_server(db, conn)
    if not check_server:
        return False, "Сервер не найден"

    if check_server.status == ServerStatus.OFFLINE:
        conn.status = ConnectionStatus.INACTIVE
        db.commit()
        return False, "Сервер недоступен"

    try:
        from app.services.ssh_service import SSHClient
        with SSHClient(check_server) as ssh:
            alive = _check_alive_on_server(ssh, conn)

        conn.status = ConnectionStatus.ACTIVE if alive else ConnectionStatus.INACTIVE
        db.commit()
        return alive, "Активно" if alive else "Не отвечает"

    except Exception as e:
        return False, f"Ошибка проверки: {e}"


def check_all_connections(db: Session) -> Dict[int, dict]:
    """Параллельная проверка всех подключений через ThreadPoolExecutor.

    Группирует подключения по фактическому серверу проверки:
    - direct любой протокол       → EU сервер (server_id)
    - cascade VLESS+Reality        → RU сервер (ru_server_id) — там слушает Xray
    - cascade NaiveProxy           → RU сервер (ru_server_id) — там caddy-naive
    - cascade AmneziaWG            → EU сервер (server_id)    — там wg-интерфейс

    Открывает одно SSH-соединение на каждый уникальный сервер.
    Возвращает dict {conn_id: {alive, status, message}}.
    """
    from app.services.ssh_service import SSHClient

    # Забираем все подключения (не в состоянии deploying)
    conns = db.query(Connection).filter(
        Connection.setup_status.in_(["done", "failed", None])
    ).all()

    if not conns:
        return {}

    # Определяем для каждого подключения — на каком сервере проверять
    # Ключ: server_id того сервера, к которому надо SSH
    by_check_server: Dict[int, List[Connection]] = {}
    for c in conns:
        is_cascade = c.connection_type == ConnectionType.CASCADE
        use_ru = (
            is_cascade
            and c.ru_server_id
            and c.protocol in (Protocol.VLESS_REALITY, Protocol.NAIVE_PROXY)
        )
        check_srv_id = c.ru_server_id if use_ru else c.server_id
        by_check_server.setdefault(check_srv_id, []).append(c)

    results: Dict[int, dict] = {}
    results_lock = threading.Lock()

    def _check_server_group(check_server_id: int, group: List[Connection]) -> None:
        """Проверяет все подключения одного сервера в одном SSH-соединении."""
        from app.db.database import SessionLocal
        thread_db = SessionLocal()
        try:
            check_server = thread_db.query(Server).filter(Server.id == check_server_id).first()
            if not check_server:
                with results_lock:
                    for c in group:
                        results[c.id] = {"alive": False, "status": "inactive", "message": "Сервер не найден"}
                return

            # Сервер offline — пропускаем SSH, ставим всем inactive
            if check_server.status == ServerStatus.OFFLINE:
                with results_lock:
                    for c in group:
                        db_conn = thread_db.query(Connection).filter(Connection.id == c.id).first()
                        if db_conn:
                            db_conn.status = ConnectionStatus.INACTIVE
                        results[c.id] = {"alive": False, "status": "inactive", "message": "Сервер недоступен"}
                thread_db.commit()
                return

            # Открываем одно SSH-соединение на нужный сервер
            try:
                with SSHClient(check_server) as ssh:
                    # Батч команд — берём все данные сразу
                    _, ss_out,  _ = ssh.exec("ss -tlnp 2>/dev/null")
                    _, ss_udp,  _ = ssh.exec("ss -ulnp 2>/dev/null")
                    _, awg_out, _ = ssh.exec("awg show 2>/dev/null || wg show 2>/dev/null")
                    _, np_out,  _ = ssh.exec("systemctl is-active caddy 2>/dev/null")

                np_alive  = np_out.strip() == "active"
                awg_alive = "interface" in awg_out.lower()

                for c in group:
                    db_conn = thread_db.query(Connection).filter(Connection.id == c.id).first()
                    if not db_conn:
                        continue

                    if c.protocol == Protocol.VLESS_REALITY:
                        # TCP порт — проверяем в ss -tlnp
                        alive = str(c.port) in ss_out
                    elif c.protocol == Protocol.AMNEZIA_WG:
                        # AWG: проверяем наличие интерфейса
                        alive = awg_alive
                    elif c.protocol == Protocol.NAIVE_PROXY:
                        # NaiveProxy: systemctl статус caddy-naive
                        alive = np_alive
                    else:
                        alive = False

                    db_conn.status = ConnectionStatus.ACTIVE if alive else ConnectionStatus.INACTIVE
                    with results_lock:
                        results[c.id] = {
                            "alive":   alive,
                            "status":  "active" if alive else "inactive",
                            "message": "Активно" if alive else "Не отвечает",
                        }

                thread_db.commit()

            except Exception as e:
                # SSH не удалось — помечаем всё как inactive
                for c in group:
                    db_conn = thread_db.query(Connection).filter(Connection.id == c.id).first()
                    if db_conn:
                        db_conn.status = ConnectionStatus.INACTIVE
                    with results_lock:
                        results[c.id] = {"alive": False, "status": "inactive", "message": f"SSH ошибка: {e}"}
                thread_db.commit()

        finally:
            thread_db.close()

    # Запускаем параллельно — по одному потоку на сервер
    max_workers = min(len(by_check_server), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_check_server_group, srv_id, grp): srv_id
            for srv_id, grp in by_check_server.items()
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error("check_all_connections worker error: %s", e)

    return results


# ─── redeploy ────────────────────────────────────────────────────────────────

def redeploy_connection(db: Session, conn: Connection) -> Tuple[bool, str]:
    """Повторно деплоит одно подключение (поднимает интерфейс/сервис заново).

    Используется кнопкой «Поднять подключение» в карточке.
    Сбрасывает setup_log перед запуском, чтобы в UI был свежий лог.
    """
    eu_server = db.query(Server).filter(Server.id == conn.server_id).first()
    if not eu_server:
        return False, "EU сервер не найден"

    # Сохраняем только id — SQLAlchemy-объекты нельзя передавать в другой поток
    # (сессия уже закрыта к моменту выполнения потока → "not bound to a Session")
    conn_id    = conn.id
    eu_srv_id  = eu_server.id
    ru_srv_id  = conn.ru_server_id  # None для direct

    # Сбрасываем лог и статус перед повторным деплоем
    conn.setup_log = ""
    conn.setup_status = "in_progress"
    conn.setup_step = "redeploy"
    conn.status = ConnectionStatus.INACTIVE
    db.commit()

    def _run():
        from app.db.database import SessionLocal
        thread_db = SessionLocal()
        try:
            thread_conn = thread_db.query(Connection).filter(Connection.id == conn_id).first()
            thread_eu   = thread_db.query(Server).filter(Server.id == eu_srv_id).first()
            thread_ru   = thread_db.query(Server).filter(Server.id == ru_srv_id).first() if ru_srv_id else None
            _deploy_one(thread_db, thread_conn, thread_eu, thread_ru)
        except Exception as e:
            logger.error("redeploy_connection error for conn %s: %s", conn_id, e)
        finally:
            thread_db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True, "Redeploy запущен"
