"""
Auto Connections Service — генерация подключений по матрице.

Матрица:
  EU без домена    → VLESS Reality (прямое), AmneziaWG (прямое)
  EU + домен EU    → + NaiveProxy EU (прямое)
  RU + EU          → + VLESS→VLESS (каскад), AWG→VLESS (каскад)
  RU + домен RU    → + NaiveProxy RU→EU (каскад)
"""

import logging
import secrets
import string
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from app.models.server import Server, ServerRole
from app.models.connection import Connection, Protocol, ConnectionStatus
from app.models.domain import Subdomain, SubdomainType
from app.services.config_generator import (
    generate_uuid, generate_password, generate_short_id,
    REALITY_SNI_DEFAULT,
)
from app.services.port_service import assign_free_port

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ПУБЛИЧНАЯ ТОЧКА ВХОДА
# ─────────────────────────────────────────────────────────────────────────────

def generate_connections_for_server(db: Session, server: Server) -> List[Dict]:
    """
    Генерирует все доступные подключения для сервера по матрице.
    Возвращает список {"name": ..., "ok": bool, "message": str, "connection_id": int|None}
    """
    results = []

    if server.role == ServerRole.EU:
        results += _generate_eu_connections(db, server)
    else:
        results += _generate_ru_connections(db, server)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# EU СЕРВЕР
# ─────────────────────────────────────────────────────────────────────────────

def _generate_eu_connections(db: Session, server: Server) -> List[Dict]:
    results = []

    # 1. VLESS Reality (прямое)
    results.append(_create_vless_direct(db, server))

    # 2. AmneziaWG (прямое)
    results.append(_create_awg_direct(db, server))

    # 3. NaiveProxy (прямое) — только если есть домен EU
    eu_domain = _find_domain(db, SubdomainType.naiveproxy_eu)
    if eu_domain:
        results.append(_create_naiveproxy_direct(db, server, eu_domain))
    else:
        results.append({
            "name": "NaiveProxy EU (прямое)",
            "ok": False,
            "message": "Домен naiveproxy_eu не найден — создайте поддомен в разделе Домены",
            "connection_id": None
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# RU СЕРВЕР
# ─────────────────────────────────────────────────────────────────────────────

def _generate_ru_connections(db: Session, server: Server) -> List[Dict]:
    results = []

    # Ищем привязанный EU-сервер
    eu_server = _get_eu_server(db, server)
    if not eu_server:
        return [{
            "name": "Каскадные подключения",
            "ok": False,
            "message": "EU-сервер не привязан — привяжите EU-сервер через интерфейс серверов",
            "connection_id": None
        }]

    # Ищем существующее VLESS Reality на EU-сервере (нужно для outbound)
    eu_vless = _find_eu_vless_connection(db, eu_server)

    # 4. VLESS Reality → VLESS Reality (каскад RU→EU)
    if eu_vless:
        results.append(_create_vless_cascade(db, server, eu_server, eu_vless))
    else:
        results.append({
            "name": "VLESS Reality (каскад RU→EU)",
            "ok": False,
            "message": "На EU-сервере нет VLESS Reality подключения",
            "connection_id": None
        })

    # 5. AmneziaWG (RU) — прямое на RU, выход через EU VLESS
    results.append(_create_awg_direct(db, server, cascade_label="(каскад RU→EU)"))

    # 6. NaiveProxy (каскад) — только если есть домен RU
    ru_domain = _find_domain(db, SubdomainType.naiveproxy_ru)
    if ru_domain:
        results.append(_create_naiveproxy_cascade(db, server, eu_server, ru_domain))
    else:
        results.append({
            "name": "NaiveProxy RU (каскад RU→EU)",
            "ok": False,
            "message": "Домен naiveproxy_ru не найден — создайте поддомен в разделе Домены",
            "connection_id": None
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# СОЗДАНИЕ КОНКРЕТНЫХ ПОДКЛЮЧЕНИЙ
# ─────────────────────────────────────────────────────────────────────────────

def _create_vless_direct(db: Session, server: Server) -> Dict:
    name = "VLESS Reality (прямое)"
    try:
        # Выбираем SNI по географии сервера
        server_name = _pick_reality_sni(server)

        conn = Connection(
            name=name,
            server_id=server.id,
            protocol=Protocol.VLESS_REALITY,
            port=443,
            uuid=generate_uuid(),
            reality_server_name=server_name,
            status=ConnectionStatus.DEPLOYING,
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        # Деплой
        from app.services import deploy_service
        ok, msg = deploy_service.deploy_vless_reality_connection(db, conn, server)
        conn.status = ConnectionStatus.ACTIVE if ok else ConnectionStatus.ERROR
        db.commit()

        return {"name": name, "ok": ok, "message": msg, "connection_id": conn.id}
    except Exception as e:
        logger.error(f"_create_vless_direct error: {e}")
        return {"name": name, "ok": False, "message": str(e), "connection_id": None}


def _create_vless_cascade(db: Session, server: Server, eu_server: Server, eu_vless: Connection) -> Dict:
    name = "VLESS Reality (каскад RU→EU)"
    try:
        server_name = _pick_reality_sni(server)

        conn = Connection(
            name=name,
            server_id=server.id,
            protocol=Protocol.VLESS_REALITY,
            port=443,
            uuid=generate_uuid(),
            reality_server_name=server_name,
            exit_server_id=eu_server.id,
            status=ConnectionStatus.DEPLOYING,
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        from app.services import deploy_service
        ok, msg = deploy_service.deploy_vless_reality_connection(db, conn, server, exit_server=eu_server)
        conn.status = ConnectionStatus.ACTIVE if ok else ConnectionStatus.ERROR
        db.commit()

        return {"name": name, "ok": ok, "message": msg, "connection_id": conn.id}
    except Exception as e:
        logger.error(f"_create_vless_cascade error: {e}")
        return {"name": name, "ok": False, "message": str(e), "connection_id": None}


def _create_awg_direct(db: Session, server: Server, cascade_label: str = "") -> Dict:
    name = f"AmneziaWG {'(прямое)' if not cascade_label else cascade_label}"
    try:
        # AWG порт — 51820 или следующий свободный
        try:
            port = assign_free_port(db, server.id, preferred_port=51820)
        except Exception:
            port = 51820

        conn = Connection(
            name=name,
            server_id=server.id,
            protocol=Protocol.AMNEZIA_WG,
            port=port,
            awg_junk_packet_count=4,
            awg_junk_packet_min_size=40,
            awg_junk_packet_max_size=70,
            status=ConnectionStatus.DEPLOYING,
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        from app.services import deploy_service
        ok, msg = deploy_service.deploy_amnezia_wg_connection(db, conn, server)
        conn.status = ConnectionStatus.ACTIVE if ok else ConnectionStatus.ERROR
        db.commit()

        return {"name": name, "ok": ok, "message": msg, "connection_id": conn.id}
    except Exception as e:
        logger.error(f"_create_awg_direct error: {e}")
        return {"name": name, "ok": False, "message": str(e), "connection_id": None}


def _create_naiveproxy_direct(db: Session, server: Server, domain: str) -> Dict:
    name = f"NaiveProxy EU (прямое) · {domain}"
    try:
        password = generate_password(24)

        try:
            port = assign_free_port(db, server.id, preferred_port=443)
        except Exception:
            port = 8443

        conn = Connection(
            name=name,
            server_id=server.id,
            protocol=Protocol.NAIVE_PROXY,
            port=port,
            password=password,
            status=ConnectionStatus.DEPLOYING,
        )
        # Временно задаём домен через server.domain для deploy_service
        _orig_domain = server.domain
        server.domain = domain

        db.add(conn)
        db.commit()
        db.refresh(conn)

        from app.services import deploy_service
        ok, msg = deploy_service.deploy_naiveproxy_connection(db, conn, server)
        server.domain = _orig_domain
        conn.status = ConnectionStatus.ACTIVE if ok else ConnectionStatus.ERROR
        db.commit()

        return {"name": name, "ok": ok, "message": msg, "connection_id": conn.id}
    except Exception as e:
        logger.error(f"_create_naiveproxy_direct error: {e}")
        return {"name": name, "ok": False, "message": str(e), "connection_id": None}


def _create_naiveproxy_cascade(db: Session, server: Server, eu_server: Server, domain: str) -> Dict:
    name = f"NaiveProxy RU (каскад RU→EU) · {domain}"
    try:
        password = generate_password(24)

        try:
            port = assign_free_port(db, server.id, preferred_port=443)
        except Exception:
            port = 8443

        conn = Connection(
            name=name,
            server_id=server.id,
            protocol=Protocol.NAIVE_PROXY,
            port=port,
            password=password,
            exit_server_id=eu_server.id,
            status=ConnectionStatus.DEPLOYING,
        )

        _orig_domain = server.domain
        server.domain = domain

        db.add(conn)
        db.commit()
        db.refresh(conn)

        from app.services import deploy_service
        ok, msg = deploy_service.deploy_naiveproxy_connection(db, conn, server)
        server.domain = _orig_domain
        conn.status = ConnectionStatus.ACTIVE if ok else ConnectionStatus.ERROR
        db.commit()

        return {"name": name, "ok": ok, "message": msg, "connection_id": conn.id}
    except Exception as e:
        logger.error(f"_create_naiveproxy_cascade error: {e}")
        return {"name": name, "ok": False, "message": str(e), "connection_id": None}


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ
# ─────────────────────────────────────────────────────────────────────────────

def _find_domain(db: Session, stype: SubdomainType) -> Optional[str]:
    sub = db.query(Subdomain).filter(Subdomain.subdomain_type == stype).first()
    return sub.full_name if sub else None


def _get_eu_server(db: Session, ru_server: Server) -> Optional[Server]:
    """Возвращает привязанный EU-сервер, если не привязан — берёт с наименьшей нагрузкой."""
    if ru_server.eu_server_id:
        return db.query(Server).filter(Server.id == ru_server.eu_server_id).first()

    # Авто: EU-сервер с минимальным числом привязанных RU
    eu_servers = db.query(Server).filter(
        Server.role == ServerRole.EU,
        Server.is_active == True
    ).all()

    if not eu_servers:
        return None

    # Считаем нагрузку: количество RU-серверов, привязанных к каждому EU
    def load(eu: Server) -> int:
        return db.query(Server).filter(
            Server.eu_server_id == eu.id
        ).count()

    best = min(eu_servers, key=load)
    # Сохраняем привязку
    ru_server.eu_server_id = best.id
    db.commit()
    return best


def _find_eu_vless_connection(db: Session, eu_server: Server) -> Optional[Connection]:
    return db.query(Connection).filter(
        Connection.server_id == eu_server.id,
        Connection.protocol == Protocol.VLESS_REALITY,
        Connection.is_active == True,
        Connection.reality_public_key.isnot(None),
    ).first()


def _pick_reality_sni(server: Server) -> str:
    """Выбирает SNI по географии сервера."""
    country = (server.country or "??").upper()
    # Для RU-серверов и стран СНГ используем нейтральный домен
    ru_adjacent = {"RU", "BY", "KZ", "UA", "UZ"}
    if country in ru_adjacent:
        return "www.microsoft.com"
    # Для EU/US — можно использовать более «западные» домены
    eu_domains = {
        "DE": "www.swift.org",
        "NL": "www.cloudflare.com",
        "FI": "www.apple.com",
        "FR": "addons.mozilla.org",
        "GB": "aws.amazon.com",
        "US": "www.amazon.com",
    }
    return eu_domains.get(country, "www.microsoft.com")
