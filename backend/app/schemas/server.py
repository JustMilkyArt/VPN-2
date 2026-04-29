from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any
from datetime import datetime
from app.models.server import ServerRole, ServerStatus


class ServerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    ip: str = Field(..., description="IP address or domain of the server")
    country: str = Field(default="??", max_length=10)
    role: ServerRole = ServerRole.EU
    ssh_user: str = Field(default="root", max_length=100)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    domain: Optional[str] = None
    notes: Optional[str] = None


class ServerCreate(ServerBase):
    ssh_key: Optional[str] = Field(None, description="Private SSH key (PEM format)")
    ssh_password: Optional[str] = Field(None, description="SSH password (if no key)")


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    role: Optional[ServerRole] = None
    ssh_user: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_key: Optional[str] = None
    ssh_password: Optional[str] = None
    domain: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ServerRead(ServerBase):
    id: int
    status: ServerStatus
    is_active: bool
    xray_installed: bool
    naiveproxy_installed: bool
    awg_installed: bool
    warp_installed: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    # ── Setup flow ──────────────────────────────────────────────────────────
    setup_status: Optional[str] = None
    setup_step: Optional[str] = None
    setup_error: Optional[str] = None

    # ── Server info (собирается после setup) ────────────────────────────────
    server_timezone: Optional[str] = None
    xray_version: Optional[str] = None
    caddy_version: Optional[str] = None
    awg_version: Optional[str] = None
    warp_version: Optional[str] = None
    xray_public_key: Optional[str] = None
    awg_server_public_key: Optional[str] = None

    # ── Флаги зашифрованных credentials (фронт получает bool, не сам ключ) ─
    ssh_private_key_enc: Optional[bool] = None   # True = приватный ключ сохранён
    ssh_password_enc: Optional[bool] = None       # True = пароль сохранён зашифровано

    # ── Актуальные SSH-данные после харденинга ───────────────────────────────
    ssh_user_actual: Optional[str] = None
    ssh_port_actual: Optional[int] = None

    # ── Security flags ───────────────────────────────────────────────────────
    sec_fail2ban:       Optional[bool] = None
    sec_ufw:            Optional[bool] = None
    sec_password_login: Optional[bool] = None
    sec_ssh_key:        Optional[bool] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def _convert_enc_and_extra(cls, data: Any) -> Any:
        """
        Преобразует SQLAlchemy-объект в dict:
        - ssh_private_key_enc / ssh_password_enc → bool (наличие значения)
        - подхватываем все поля модели
        """
        if not hasattr(data, '__class__') or isinstance(data, dict):
            return data

        fields = [
            'id', 'name', 'ip', 'country', 'role', 'ssh_user', 'ssh_port',
            'domain', 'notes', 'status', 'is_active',
            'xray_installed', 'naiveproxy_installed', 'awg_installed', 'warp_installed',
            'created_at', 'updated_at',
            'setup_status', 'setup_step', 'setup_error',
            'server_timezone', 'xray_version', 'caddy_version', 'awg_version',
            'warp_version', 'xray_public_key', 'awg_server_public_key',
            'ssh_user_actual', 'ssh_port_actual',
            'sec_fail2ban', 'sec_ufw', 'sec_password_login', 'sec_ssh_key',
        ]
        result = {}
        for f in fields:
            val = getattr(data, f, None)
            if val is not None:
                result[f] = val

        # Зашифрованные поля — только наличие
        pk_enc = getattr(data, 'ssh_private_key_enc', None)
        pw_enc = getattr(data, 'ssh_password_enc', None)
        ssh_key_plain = getattr(data, 'ssh_key', None)   # plain key тоже считаем
        result['ssh_private_key_enc'] = bool(pk_enc or ssh_key_plain)
        ssh_pass_plain = getattr(data, 'ssh_password', None)
        result['ssh_password_enc'] = bool(pw_enc or ssh_pass_plain)

        return result


class ServerStatusUpdate(BaseModel):
    is_active: bool


class ServerInstallRequest(BaseModel):
    install_xray: bool = True
    install_naiveproxy: bool = False
    install_awg: bool = False
    install_warp: bool = False


class ServerRebootRequest(BaseModel):
    pass


class ServerChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, description="New SSH password")


class ServerChangeSSHKeyRequest(BaseModel):
    ssh_key: str = Field(..., description="New SSH private key (PEM format)")


class ServerUninstallStackRequest(BaseModel):
    uninstall_xray: bool = False
    uninstall_naiveproxy: bool = False
    uninstall_awg: bool = False
    uninstall_warp: bool = False
