from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser
from app.models.server import Server
from app.schemas.server import ServerCreate, ServerUpdate, ServerRead, ServerInstallRequest
from app.services import server_service, deploy_service
from app.services.ssh_service import test_connection

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get("/", response_model=List[ServerRead])
def list_servers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    return server_service.get_servers(db, skip=skip, limit=limit)


@router.post("/", response_model=ServerRead, status_code=status.HTTP_201_CREATED)
def create_server(
    server_data: ServerCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    return server_service.create_server(db, server_data)


@router.get("/{server_id}", response_model=ServerRead)
def get_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.put("/{server_id}", response_model=ServerRead)
def update_server(
    server_id: int,
    update_data: ServerUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server_service.update_server(db, server, update_data)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server_service.delete_server(db, server)


@router.post("/{server_id}/ping", summary="Test SSH connection")
def ping_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    status_result = server_service.check_server_status(db, server)
    ok, msg = test_connection(server)
    return {
        "server_id": server_id,
        "status": status_result,
        "message": msg,
        "reachable": ok
    }


@router.get("/{server_id}/info", summary="Get server system info")
def server_info(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server_service.get_server_details(server)


@router.post("/{server_id}/install", summary="Install VPN stack on server")
def install_stack(
    server_id: int,
    install_req: ServerInstallRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    results = {}
    
    if install_req.install_xray:
        ok, msg = deploy_service.install_xray(server)
        results["xray"] = {"success": ok, "message": msg}
        if ok:
            server.xray_installed = True
    
    if install_req.install_warp:
        ok, msg = deploy_service.install_warp(server)
        results["warp"] = {"success": ok, "message": msg}
        if ok:
            server.warp_installed = True
    
    db.commit()
    return {"server_id": server_id, "results": results}


@router.post("/{server_id}/restart", summary="Restart VPN services on server")
def restart_services(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    ok, msg = deploy_service.restart_services(server)
    return {"success": ok, "message": msg}


@router.post("/{server_id}/redeploy", summary="Redeploy all configs to server")
def redeploy_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    ok, msg = deploy_service.redeploy_server_config(db, server)
    return {"success": ok, "message": msg}


@router.post("/check-all-status", summary="Check status of all servers")
def check_all_status(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    servers = server_service.get_servers(db)
    results = {}
    for server in servers:
        status_res = server_service.check_server_status(db, server)
        results[server.id] = {
            "name": server.name,
            "ip": server.ip,
            "status": status_res
        }
    return results
