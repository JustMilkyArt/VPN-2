"""
Initialize database and create default Creator account.
"""
import logging
from app.core.config import settings
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def create_tables():
    from app.db.database import Base, engine
    import app.models.server       # noqa: F401
    import app.models.connection   # noqa: F401
    import app.models.admin_user   # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def create_default_admin():
    """
    Create default Creator account if no users exist.
    TOTP is generated immediately — the secret is logged once so the
    operator can add it to their authenticator app on first launch.
    Login requires: username + password + TOTP code (always).
    """
    from app.db.database import SessionLocal
    from app.models.admin_user import AdminUser, UserRole
    from app.services.totp_service import generate_totp_secret, get_totp_uri

    db = SessionLocal()
    try:
        count = db.query(AdminUser).count()
        if count == 0:
            secret = generate_totp_secret()
            creator = AdminUser(
                username=settings.ADMIN_USERNAME,
                password_hash=get_password_hash(settings.ADMIN_PASSWORD),
                role=UserRole.creator,
                totp_secret=secret,
                totp_enabled=True,
                is_active=True,
            )
            db.add(creator)
            db.commit()

            uri = get_totp_uri(secret, settings.ADMIN_USERNAME)
            logger.info("=" * 60)
            logger.info("CREATOR ACCOUNT CREATED")
            logger.info(f"  Username : {settings.ADMIN_USERNAME}")
            logger.info(f"  Password : (see ADMIN_PASSWORD in .env)")
            logger.info(f"  TOTP key : {secret}")
            logger.info(f"  TOTP URI : {uri}")
            logger.info("Add this key to your authenticator app NOW.")
            logger.info("It will NOT be shown again.")
            logger.info("=" * 60)
        else:
            logger.info(f"Users exist ({count}), skipping default creator creation")
    except Exception as e:
        logger.error(f"Error creating default admin: {e}")
        db.rollback()
    finally:
        db.close()


def init_db():
    create_tables()
    create_default_admin()
