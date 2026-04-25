from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser
from app.models.server import Server, ServerRole
from app.schemas.server import (
    ServerCreate, ServerUpdate, ServerRead, ServerInstallRequest,
    ServerChangePasswordRequest, ServerChangeSSHKeyRequest, ServerUninstallStackRequest
)
from app.services import server_service, deploy_service
from app.services.ssh_service import (
    test_connection, ping_with_latency, reboot_server,
    change_ssh_password, add_ssh_key, uninstall_stack,
    harden_server, get_security_status, apply_security_setting
)

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Создаёт сервер в БД. Автонастройка запускается через SSE /setup.
    Для EU-серверов сразу запускает базовое hardening в фоне (fail2ban, ufw).
    """
    from app.models.server import SetupStatus
    server = server_service.create_server(db, server_data)
    # НЕ запускаем автонастройку здесь — она идёт через SSE /setup
    # Но для EU-серверов запускаем базовое hardening в фоне немедленно
    # (защита сервера пока идёт полная автонастройка)
    from app.models.server import ServerRole
    if server.role == ServerRole.EU:
        background_tasks.add_task(harden_server, server)
    return server


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


@router.post("/{server_id}/ping", summary="Test SSH connection with latency")
def ping_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    ok, msg, latency_ms = ping_with_latency(server)

    # Update status in DB
    from app.models.server import ServerStatus
    server.status = ServerStatus.ONLINE if ok else ServerStatus.OFFLINE
    db.commit()

    return {
        "server_id": server_id,
        "reachable": ok,
        "message": msg,
        "latency_ms": latency_ms,
        "status": server.status
    }



@router.get("/{server_id}/stats", summary="Get connection statistics for server")
def server_stats(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    from app.models.connection import Connection, ConnectionStatus
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    all_conns = db.query(Connection).filter(Connection.server_id == server_id).all()
    active = [c for c in all_conns if c.status == ConnectionStatus.ACTIVE]

    # Разбивка по протоколам
    proto_counts = {}
    for c in active:
        p = c.protocol or "unknown"
        proto_counts[p] = proto_counts.get(p, 0) + 1

    return {
        "server_id": server_id,
        "total": len(all_conns),
        "active": len(active),
        "inactive": len([c for c in all_conns if c.status == ConnectionStatus.INACTIVE]),
        "error": len([c for c in all_conns if c.status == ConnectionStatus.ERROR]),
        "protocols": proto_counts,
    }


@router.post("/{server_id}/stats", summary="Refresh and get connection statistics")
def refresh_server_stats(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Same as GET /stats but allows POST for explicit refresh triggers from frontend."""
    from app.models.connection import Connection, ConnectionStatus
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    all_conns = db.query(Connection).filter(Connection.server_id == server_id).all()
    active = [c for c in all_conns if c.status == ConnectionStatus.ACTIVE]

    proto_counts = {}
    for c in active:
        p = c.protocol or "unknown"
        proto_counts[p] = proto_counts.get(p, 0) + 1

    return {
        "server_id": server_id,
        "total": len(all_conns),
        "active": len(active),
        "inactive": len([c for c in all_conns if c.status == ConnectionStatus.INACTIVE]),
        "error": len([c for c in all_conns if c.status == ConnectionStatus.ERROR]),
        "protocols": proto_counts,
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

    if install_req.install_naiveproxy:
        ok, msg = deploy_service.install_naiveproxy(server)
        results["naiveproxy"] = {"success": ok, "message": msg}
        if ok:
            server.naiveproxy_installed = True

    if install_req.install_awg:
        ok, msg = deploy_service.install_amnezia_wg(server)
        results["awg"] = {"success": ok, "message": msg}
        if ok:
            server.awg_installed = True

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


@router.post("/{server_id}/reboot", summary="Reboot the server OS")
def reboot_server_endpoint(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    ok, msg = reboot_server(server)
    if ok:
        # Mark as unknown while it reboots
        from app.models.server import ServerStatus
        server.status = ServerStatus.UNKNOWN
        db.commit()
    return {"success": ok, "message": msg}


@router.post("/{server_id}/change-password", summary="Change SSH user password")
def change_password_endpoint(
    server_id: int,
    req: ServerChangePasswordRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    ok, msg = change_ssh_password(server, req.new_password)
    if ok:
        # Update stored password in DB
        server.ssh_password = req.new_password
        db.commit()
    return {"success": ok, "message": msg}


@router.post("/{server_id}/add-ssh-key", summary="Add SSH public key to server")
def add_ssh_key_endpoint(
    server_id: int,
    req: ServerChangeSSHKeyRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    ok, msg = add_ssh_key(server, req.ssh_key)
    if ok:
        # Store public key reference in notes (private key stored separately if needed)
        server.ssh_key = req.ssh_key
        db.commit()
    return {"success": ok, "message": msg}


@router.post("/{server_id}/uninstall-stack", summary="Remove VPN services from server")
def uninstall_stack_endpoint(
    server_id: int,
    req: ServerUninstallStackRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    services = []
    if req.uninstall_xray:
        services.append("xray")
    if req.uninstall_naiveproxy:
        services.append("naiveproxy")
    if req.uninstall_awg:
        services.append("awg")
    if req.uninstall_warp:
        services.append("warp")

    if not services:
        raise HTTPException(status_code=400, detail="No services selected for uninstall")

    ok, msg = uninstall_stack(server, services)
    if ok:
        if req.uninstall_xray:
            server.xray_installed = False
        if req.uninstall_naiveproxy:
            server.naiveproxy_installed = False
        if req.uninstall_awg:
            server.awg_installed = False
        if req.uninstall_warp:
            server.warp_installed = False
        db.commit()
    return {"success": ok, "message": msg}


@router.get("/{server_id}/security", summary="Get real security status from server")
def get_security(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return get_security_status(server)


class SecuritySettingRequest(BaseModel):
    setting: str   # fail2ban | ufw | password_login | root_login
    enabled: bool


@router.post("/{server_id}/security", summary="Apply a security setting on server")
def set_security(
    server_id: int,
    req: SecuritySettingRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    ok, msg = apply_security_setting(server, req.setting, req.enabled)
    return {"success": ok, "message": msg}


@router.post("/{server_id}/harden", summary="Run basic hardening (UFW + Fail2Ban)")
def harden_server_endpoint(
    server_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    background_tasks.add_task(harden_server, server)
    return {"success": True, "message": "Hardening started in background"}


# ─────────────────────────────────────────────────────────────────────────────
# SSE: Автонастройка сервера (прогресс-экран)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{server_id}/setup", summary="SSE stream: auto-setup server (steps 1-7)")
async def setup_server_sse(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Server-Sent Events поток для прогресс-экрана автонастройки."""
    from app.services.setup_service import run_server_setup
    import json

    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    async def event_stream():
        async for chunk in run_server_setup(db, server):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/{server_id}/setup/retry", summary="SSE stream: retry setup from step 4")
async def retry_setup_server_sse(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Повтор автонастройки с шага 4 (стек и дальше)."""
    from app.services.setup_service import retry_server_setup

    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    async def event_stream():
        async for chunk in retry_server_setup(db, server):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/{server_id}/link-eu", summary="Link RU server to EU server")
def link_eu_server(
    server_id: int,
    eu_server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Привязывает RU-сервер к EU-серверу (drag-and-drop из UI)."""
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if server.role != ServerRole.RU:
        raise HTTPException(status_code=400, detail="Only RU servers can be linked to EU")

    eu = server_service.get_server(db, eu_server_id)
    if not eu:
        raise HTTPException(status_code=404, detail="EU server not found")
    if eu.role != ServerRole.EU:
        raise HTTPException(status_code=400, detail="Target server is not EU")

    server.eu_server_id = eu_server_id
    db.commit()
    db.refresh(server)
    return {"success": True, "message": f"RU сервер {server.name} привязан к EU {eu.name}"}


@router.delete("/{server_id}/link-eu", summary="Unlink RU server from EU server")
def unlink_eu_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.eu_server_id = None
    db.commit()
    return {"success": True, "message": "Привязка к EU-серверу снята"}



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
