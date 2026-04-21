"""
Domain management API.
Accessible only to creator and head_admin roles.
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.admin_user import AdminUser, UserRole
from app.models.domain import Domain, Subdomain, DomainStatus, SubdomainStatus, SubdomainType
from app.schemas.domain import DomainCreate, DomainRead, SubdomainCreate, SubdomainRead, SubdomainStatusRead
from app.services import porkbun_service
from app.services.domain_setup_service import run_subdomain_setup
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/domains", tags=["domains"])


def _require_domain_admin(
    current_user: AdminUser = Depends(get_current_user),
) -> AdminUser:
    """Allow only creator and head_admin to manage domains."""
    if current_user.role not in (UserRole.creator, UserRole.head_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль creator или head_admin."
        )
    return current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _domain_or_404(db: Session, domain_id: int) -> Domain:
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Домен не найден")
    return d


def _subdomain_or_404(db: Session, domain_id: int, subdomain_id: int) -> Subdomain:
    s = (
        db.query(Subdomain)
        .filter(Subdomain.id == subdomain_id, Subdomain.domain_id == domain_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Поддомен не найден")
    return s


# ── Domain CRUD ───────────────────────────────────────────────────────────────

@router.post("/", response_model=DomainRead)
async def add_domain(
    payload: DomainCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """Add a new domain and validate Porkbun API credentials."""
    # Check uniqueness
    existing = db.query(Domain).filter(Domain.name == payload.name.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Домен уже добавлен")

    # Validate Porkbun keys
    try:
        ip = await porkbun_service.ping(payload.porkbun_api_key, payload.porkbun_secret_key)
        status = DomainStatus.active
        message = f"API-ключи подтверждены. Ваш IP: {ip}"
    except porkbun_service.PorkbunError as e:
        status = DomainStatus.error
        message = f"Ошибка проверки API-ключей: {e}"

    domain = Domain(
        name=payload.name.lower().strip(),
        porkbun_api_key=payload.porkbun_api_key,
        porkbun_secret_key=payload.porkbun_secret_key,
        status=status,
        status_message=message,
    )
    db.add(domain)
    db.commit()
    db.refresh(domain)
    logger.info(f"Domain {domain.name} added by {current_user.username}, status={status}")
    return domain


@router.get("/", response_model=list[DomainRead])
def list_domains(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """List all domains with their subdomains."""
    return db.query(Domain).order_by(Domain.created_at.desc()).all()


@router.delete("/{domain_id}")
def delete_domain(
    domain_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """Delete a domain and all its subdomains."""
    domain = _domain_or_404(db, domain_id)
    db.delete(domain)
    db.commit()
    return {"ok": True, "detail": f"Домен {domain.name} удалён"}


# ── Subdomain CRUD ────────────────────────────────────────────────────────────

@router.post("/{domain_id}/subdomains/", response_model=SubdomainRead)
async def create_subdomain(
    domain_id: int,
    payload: SubdomainCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """
    Create a subdomain and launch background setup task.
    For admin_panel / client_site: full DNS + SSL + Nginx pipeline.
    For vpn / none: reserve only.
    """
    domain = _domain_or_404(db, domain_id)

    # Validate domain is active
    if domain.status != DomainStatus.active:
        raise HTTPException(
            status_code=400,
            detail="Домен не активен. Проверьте API-ключи Porkbun."
        )

    subdomain_name = payload.name.lower().strip().replace(" ", "-")
    full_name = f"{subdomain_name}.{domain.name}"

    # Check uniqueness
    existing = db.query(Subdomain).filter(Subdomain.full_name == full_name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Поддомен {full_name} уже существует")

    # Determine target IP
    target_ip = payload.target_ip or settings.ADMIN_SERVER_IP

    subdomain = Subdomain(
        domain_id=domain_id,
        name=subdomain_name,
        full_name=full_name,
        subdomain_type=SubdomainType(payload.subdomain_type),
        target_ip=target_ip,
        status=SubdomainStatus.pending,
    )
    db.add(subdomain)
    db.commit()
    db.refresh(subdomain)

    logger.info(f"Subdomain {full_name} created, launching setup task")

    # Launch background setup
    background_tasks.add_task(run_subdomain_setup, subdomain.id)

    return subdomain


@router.get("/{domain_id}/subdomains/", response_model=list[SubdomainRead])
def list_subdomains(
    domain_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """List all subdomains for a domain."""
    _domain_or_404(db, domain_id)
    return (
        db.query(Subdomain)
        .filter(Subdomain.domain_id == domain_id)
        .order_by(Subdomain.created_at.desc())
        .all()
    )


@router.get("/{domain_id}/subdomains/{subdomain_id}/status", response_model=SubdomainStatusRead)
def get_subdomain_status(
    domain_id: int,
    subdomain_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """Poll subdomain setup status (called every 2s from frontend)."""
    s = _subdomain_or_404(db, domain_id, subdomain_id)
    return s


@router.delete("/{domain_id}/subdomains/{subdomain_id}")
async def delete_subdomain(
    domain_id: int,
    subdomain_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """Delete a subdomain (optionally removes DNS record via Porkbun)."""
    subdomain = _subdomain_or_404(db, domain_id, subdomain_id)
    domain = _domain_or_404(db, domain_id)

    # Try to remove DNS record if it exists
    if subdomain.dns_record_id:
        try:
            await porkbun_service.delete_dns_record(
                domain=domain.name,
                record_id=subdomain.dns_record_id,
                api_key=domain.porkbun_api_key,
                secret_key=domain.porkbun_secret_key,
            )
            logger.info(f"DNS record {subdomain.dns_record_id} deleted for {subdomain.full_name}")
        except Exception as e:
            logger.warning(f"Could not delete DNS record for {subdomain.full_name}: {e}")

    full_name = subdomain.full_name
    db.delete(subdomain)
    db.commit()
    return {"ok": True, "detail": f"Поддомен {full_name} удалён"}


@router.post("/{domain_id}/subdomains/{subdomain_id}/renew-ssl")
async def renew_ssl(
    domain_id: int,
    subdomain_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(_require_domain_admin),
):
    """Trigger SSL certificate renewal for a subdomain."""
    subdomain = _subdomain_or_404(db, domain_id, subdomain_id)
    subdomain.status = SubdomainStatus.in_progress
    subdomain.status_message = "Обновление SSL-сертификата..."
    db.add(subdomain)
    db.commit()

    background_tasks.add_task(run_subdomain_setup, subdomain.id)
    return {"ok": True, "detail": "Обновление SSL запущено"}
