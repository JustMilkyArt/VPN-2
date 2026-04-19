"""
Initialize database and create default Creator account.
Avoids circular imports by using late/local imports.
"""
import logging
from app.core.config import settings
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def create_tables():
    """Create all database tables."""
    from app.db.database import Base, engine
    import app.models.server       # noqa: F401
    import app.models.connection   # noqa: F401
    import app.models.admin_user   # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def create_default_admin():
    """Create default Creator account if no users exist at all."""
    from app.db.database import SessionLocal
    from app.models.admin_user import AdminUser, UserRole

    db = SessionLocal()
    try:
        count = db.query(AdminUser).count()
        if count == 0:
            from app.services.totp_service import generate_totp_secret
            secret = generate_totp_secret()
            creator = AdminUser(
                username=settings.ADMIN_USERNAME,
                password_hash=get_password_hash(settings.ADMIN_PASSWORD),
                role=UserRole.creator,
                totp_secret=secret,
                totp_enabled=False,       # not yet confirmed
                force_change_creds=True,  # must change on first login
                is_active=True,
            )
            db.add(creator)
            db.commit()
            logger.info(
                f"Created default Creator account: {settings.ADMIN_USERNAME}"
                " (must change credentials on first login)"
            )
        else:
            logger.info(f"Users already exist ({count}), skipping default creator creation")
    except Exception as e:
        logger.error(f"Error creating default admin: {e}")
        db.rollback()
    finally:
        db.close()


def init_db():
    """Full database initialization."""
    create_tables()
    create_default_admin()
