"""
Connections API — новые эндпоинты для wizard создания, поллинга логов, grouped view.
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import re

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser
from app.models.server import Server, ServerRole
from app.services import connection_service
from app.services.config_generator import REALITY_SNI_LIST

router = APIRouter(prefix="/connections", tags=["connections"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class ConnectionCreateRequest(BaseModel):
    eu_server_id:   int
    ru_server_id:   Optional[int] = None
    create_direct:  bool = True
    create_cascade: bool = False


class PatchParamRequest(BaseModel):
    field: str
    value: object


# ─── Вспомогательные ────────────────────────────────────────────────────────

@router.get("/sni-list", summary="Список SNI доменов для VLESS+Reality")
def get_sni_list(_: AdminUser = Depends(get_current_user)):
    return REALITY_SNI_LIST


@router.get("/available-servers", summary="Доступные серверы для wizard")
def get_available_servers(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Возвращает списки EU и RU серверов для выбора в wizard."""
    eu_servers = db.query(Server).filter(
        Server.role == ServerRole.EU,
        Server.is_active == True
    ).all()
    ru_servers = db.query(Server).filter(
        Server.role == ServerRole.RU,
        Server.is_active == True
    ).all()
    return {
        "eu_servers": [
            {"id": s.id, "name": s.name, "ip": s.ip, "country": s.country, "status": s.status}
            for s in eu_servers
        ],
        "ru_servers": [
            {"id": s.id, "name": s.name, "ip": s.ip, "country": s.country, "status": s.status}
            for s in ru_servers
        ],
        "can_direct":  len(eu_servers) > 0,
        "can_cascade": len(eu_servers) > 0 and len(ru_servers) > 0,
    }


# ─── Grouped list для UI ────────────────────────────────────────────────────

@router.get("/grouped", summary="Подключения, сгруппированные по EU серверу")
def list_connections_grouped(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    return connection_service.get_connections_grouped(db)


# ─── Wizard: создать все подключения ────────────────────────────────────────

@router.post("/batch", summary="Создать все подключения (wizard)", status_code=status.HTTP_201_CREATED)
def create_connections_batch(
    req: ConnectionCreateRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """
    Создаёт 3–6 подключений (все протоколы × выбранные типы).
    Деплой идёт в фоне. Возвращает список id для поллинга.
    """
    if not req.create_direct and not req.create_cascade:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один тип подключения")

    try:
        conn_ids = connection_service.create_connections_batch(
            db=db,
            eu_server_id=req.eu_server_id,
            ru_server_id=req.ru_server_id,
            create_direct=req.create_direct,
            create_cascade=req.create_cascade,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"connection_ids": conn_ids, "total": len(conn_ids)}


# ─── Поллинг статуса создания ───────────────────────────────────────────────

@router.get("/batch-status", summary="Статус пакетного создания")
def get_batch_status(
    ids: str,  # "1,2,3,4,5,6"
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Polling endpoint: возвращает статус и логи каждого из созданных подключений."""
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ids")

    results = []
    all_done = True
    any_failed = False

    for cid in id_list:
        conn = connection_service.get_connection(db, cid)
        if not conn:
            continue
        log_lines = (conn.setup_log or "").splitlines()
        results.append({
            "id":           cid,
            "protocol":     conn.protocol,
            "connection_type": conn.connection_type,
            "setup_status": conn.setup_status,
            "setup_step":   conn.setup_step,
            "setup_error":  conn.setup_error,
            "log_lines":    log_lines,
            "status":       conn.status,
        })
        if conn.setup_status not in ("done", "failed"):
            all_done = False
        if conn.setup_status == "failed":
            any_failed = True

    return {
        "connections": results,
        "all_done":    all_done,
        "any_failed":  any_failed,
    }


# ─── CRUD ───────────────────────────────────────────────────────────────────

@router.get("/{connection_id}", summary="Детали подключения")
def get_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    return connection_service._conn_row(db, conn)


@router.patch("/{connection_id}/param", summary="Изменить один параметр подключения")
def patch_param(
    connection_id: int,
    req: PatchParamRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    ok, msg = connection_service.patch_connection_param(db, conn, req.field, req.value)
    return {"ok": ok, "message": msg}


@router.post("/{connection_id}/check", summary="Проверить живость подключения")
def check_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    alive, msg = connection_service.check_connection_live(db, conn)
    return {"alive": alive, "message": msg, "status": conn.status}


@router.post("/{connection_id}/toggle", summary="Включить/выключить подключение")
def toggle_connection(
    connection_id: int,
    active: bool,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    updated = connection_service.toggle_connection(db, conn, active)
    return {"id": updated.id, "is_active": updated.is_active, "status": updated.status}


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    connection_service.delete_connection(db, conn)


# ─── Конфиг для клиента ─────────────────────────────────────────────────────

@router.get("/{connection_id}/client-config", summary="Получить клиентский конфиг")
def get_client_config(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    return {
        "id":          conn.id,
        "protocol":    conn.protocol,
        "client_link": conn.client_link,
        "config_text": conn.config_text,
        "config_qr":   conn.config_qr,
        "port":        conn.port,
    }


@router.get("/{connection_id}/download", summary="Скачать конфиг-файл")
def download_config(
    connection_id: int,
    db: Session = Depends(get_db),
):  # Без авторизации — файл скачивается браузером напрямую через window.open
    """
    Скачивает конфиг-файл с правильным именем.
    - AWG → <name>.conf  (Amnezia читает имя туннеля из имени файла)
    - NaiveProxy → <name>.json
    - VLESS → <name>.txt
    """
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение не найдено")

    # Формируем красивое имя файла
    server = conn.server
    srv_name = getattr(server, "display_name", "") or getattr(server, "name", "") or getattr(server, "ip", "server")
    proto_label = {
        "vless_reality": "VLESS",
        "amnezia_wg":    "AWG",
        "naive_proxy":   "NaiveProxy",
    }.get(conn.protocol, conn.protocol)
    conn_type = conn.connection_type if isinstance(conn.connection_type, str) else (conn.connection_type.value if conn.connection_type else "direct")
    # Имя файла = "FIN 1 - AWG (direct)" → безопасное для FS
    raw_name = f"{srv_name} - {proto_label} ({conn_type})"
    safe_name = re.sub(r'[^\w\s\-\(\)]', '', raw_name).strip()

    if conn.protocol == "amnezia_wg":
        content = (conn.config_text or "").encode("utf-8")
        filename = f"{safe_name}.conf"
        media_type = "text/plain"
    elif conn.protocol == "naive_proxy":
        content = (conn.config_text or conn.client_link or "").encode("utf-8")
        filename = f"{safe_name}.json"
        media_type = "application/json"
    else:
        content = (conn.client_link or conn.config_text or "").encode("utf-8")
        filename = f"{safe_name}.txt"
        media_type = "text/plain"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": f"{media_type}; charset=utf-8",
        }
    )
