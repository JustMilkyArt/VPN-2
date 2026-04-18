"""
Initialize database and create default admin user.
"""
import logging
from sqlalchemy.orm import Session
from app.db.database import Base, engine, SessionLocal
from app.models import Server, Connection, AdminUser
from app.core.config import settings
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def create_default_admin(db: Session):
    """Create default admin user if not exists."""
    existing = db.query(AdminUser).filter(AdminUser.username == settings.ADMIN_USERNAME).first()
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


def init_db():
    """Full database initialization."""
    create_tables()
    db = SessionLocal()
    try:
        create_default_admin(db)
    finally:
        db.close()
