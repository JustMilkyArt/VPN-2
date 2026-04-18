from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser
from app.schemas.connection import ConnectionCreate, ConnectionUpdate, ConnectionRead
from app.services import connection_service

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/", response_model=List[ConnectionRead])
def list_connections(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    return connection_service.get_connections(db, skip=skip, limit=limit)


@router.get("/grouped", summary="Get connections grouped by server")
def list_connections_grouped(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    return connection_service.get_connections_grouped_by_server(db)


@router.post("/", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
def create_connection(
    conn_data: ConnectionCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    connection, ok, msg = connection_service.create_connection(db, conn_data)
    if connection is None:
        raise HTTPException(status_code=400, detail=msg)
    
    if not ok:
        # Return connection with error status and detail
        return connection
    
    return connection


@router.get("/{connection_id}", response_model=ConnectionRead)
def get_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.put("/{connection_id}", response_model=ConnectionRead)
def update_connection(
    connection_id: int,
    update_data: ConnectionUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection_service.update_connection(db, conn, update_data)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    connection_service.delete_connection(db, conn)


@router.post("/{connection_id}/toggle", summary="Enable/disable connection")
def toggle_connection(
    connection_id: int,
    active: bool,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    updated = connection_service.toggle_connection(db, conn, active)
    return {"id": updated.id, "is_active": updated.is_active, "status": updated.status}


@router.get("/{connection_id}/client-config", summary="Get client connection config/link")
def get_client_config(
    connection_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    conn = connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    return {
        "id": conn.id,
        "name": conn.name,
        "protocol": conn.protocol,
        "port": conn.port,
        "client_link": conn.client_link,
        "config_json": conn.config_json,
        "uuid": conn.uuid,
        "password": conn.password,
        "reality_public_key": conn.reality_public_key,
        "reality_short_id": conn.reality_short_id,
        "reality_server_name": conn.reality_server_name,
    }
