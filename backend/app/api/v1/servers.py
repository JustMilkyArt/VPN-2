from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser
from app.models.server import Server
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
    server = server_service.create_server(db, server_data)
    # harden_server убран — его задачи выполняет run_server_setup (шаг 3)
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

from fastapi.responses import StreamingResponse
import json as _json
import time as _time
from app.services.setup_service import run_server_setup


@router.post("/{server_id}/setup", summary="Start automated server setup")
def start_setup(
    server_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if getattr(server, "setup_status", None) == "in_progress":
        return {"success": False, "message": "Setup already in progress"}
    background_tasks.add_task(run_server_setup, server_id)
    return {"success": True, "message": "Setup started"}


@router.get("/{server_id}/setup-stream", summary="SSE stream of setup progress")
def setup_stream(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    def event_generator():
        from app.db.database import SessionLocal
        local_db = SessionLocal()
        try:
            last_log_len = 0
            timeout = 600
            start = _time.time()
            while _time.time() - start < timeout:
                local_db.expire_all()
                srv = local_db.query(Server).filter(Server.id == server_id).first()
                if not srv:
                    yield "data: " + _json.dumps({"error": "Server not found"}) + "\n\n"
                    break
                log = srv.setup_log or ""
                if len(log) > last_log_len:
                    new_lines = log[last_log_len:].strip().splitlines()
                    for line in new_lines:
                        if line.strip():
                            payload = {"type": "log", "line": line.strip(),
                                       "step": srv.setup_step or "", "status": srv.setup_status or ""}
                            yield "data: " + _json.dumps(payload) + "\n\n"
                    last_log_len = len(log)
                if srv.setup_status in ("done", "failed"):
                    payload = {"type": "done", "status": srv.setup_status,
                               "error": srv.setup_error or "", "step": srv.setup_step or ""}
                    yield "data: " + _json.dumps(payload) + "\n\n"
                    break
                _time.sleep(1.5)
        finally:
            local_db.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{server_id}/setup/status", summary="Get setup status (polling)")
def get_setup_status(
    server_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Лёгкий polling-endpoint для JS: возвращает текущий статус настройки."""
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    log_raw = getattr(server, "setup_log", "") or ""
    log_lines = [l.strip() for l in log_raw.splitlines() if l.strip()]

    return {
        "setup_status": getattr(server, "setup_status", None),
        "setup_step":   getattr(server, "setup_step",   None),
        "setup_error":  getattr(server, "setup_error",  None),
        "log":          log_lines,
    }


@router.post("/{server_id}/setup/retry", summary="Retry automated server setup")
def retry_setup(
    server_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_user)
):
    """Повторный запуск автонастройки (сбрасывает статус и запускает заново)."""
    server = server_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    # Сбрасываем предыдущий статус
    server.setup_status = None
    server.setup_step   = None
    server.setup_error  = None
    server.setup_log    = None
    db.commit()
    background_tasks.add_task(run_server_setup, server_id)
    return {"success": True, "message": "Setup restarted"}
