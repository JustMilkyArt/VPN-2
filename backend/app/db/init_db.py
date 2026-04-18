"""
Initialize database and create default admin user.
Avoids circular imports by using late/local imports.
"""
import logging
from app.core.config import settings
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def create_tables():
    """Create all database tables."""
    # Late import to avoid circular dependency issues
    from app.db.database import Base, engine
    # Must import all models so SQLAlchemy registers them before create_all
    import app.models.server       # noqa: F401
    import app.models.connection   # noqa: F401
    import app.models.admin_user   # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def create_default_admin():
    """Create default admin user if not exists."""
    from app.db.database import SessionLocal
    from app.models.admin_user import AdminUser

    db = SessionLocal()
    try:
        existing = db.query(AdminUser).filter(
            AdminUser.username == settings.ADMIN_USERNAME
        ).first()
        if not existing:
            admin = AdminUser(
                username=settings.ADMIN_USERNAME,
                password_hash=get_password_hash(settings.ADMIN_PASSWORD),
            )
            db.add(admin)
            db.commit()
            logger.info(f"Created default admin user: {settings.ADMIN_USERNAME}")
        else:
            logger.info("Admin user already exists")
    except Exception as e:
        logger.error(f"Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()


def init_db():
    """Full database initialization."""
    create_tables()
    create_default_admin()
