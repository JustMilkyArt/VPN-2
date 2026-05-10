"""
Initialize database and create default Creator account.
"""
import logging
from app.core.config import settings
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def _migrate_add_columns():
    """Add new columns to existing tables (SQLite ALTER TABLE migration)."""
    from app.db.database import engine
    import sqlalchemy as sa
    try:
        with engine.connect() as conn:
            # Check existing columns in connections table
            result = conn.execute(sa.text("PRAGMA table_info(connections)"))
            existing = {row[1] for row in result.fetchall()}

            new_cols = [
                ("wg_private_key",           "VARCHAR(255)"),
                ("wg_public_key",            "VARCHAR(255)"),
                ("wg_preshared_key",         "VARCHAR(255)"),
                ("wg_client_private_key",    "VARCHAR(255)"),
                ("wg_client_public_key",     "VARCHAR(255)"),
                ("wg_client_ip",             "VARCHAR(20)"),
                ("awg_junk_packet_count",    "INTEGER DEFAULT 4"),
                ("awg_junk_packet_min_size", "INTEGER DEFAULT 40"),
                ("awg_junk_packet_max_size", "INTEGER DEFAULT 70"),
                ("connection_type",          "VARCHAR(10) DEFAULT 'direct'"),
                ("ru_server_id",             "INTEGER"),
                ("reality_fingerprint",      "VARCHAR(32) DEFAULT 'chrome'"),
                ("awg_s1",                   "INTEGER DEFAULT 50"),
                ("awg_s2",                   "INTEGER DEFAULT 100"),
                ("awg_h1",                   "INTEGER DEFAULT 1"),
                ("awg_h2",                   "INTEGER DEFAULT 2"),
                ("awg_h3",                   "INTEGER DEFAULT 3"),
                ("awg_h4",                   "INTEGER DEFAULT 4"),
                ("np_domain",                "VARCHAR(255)"),
                ("np_user",                  "VARCHAR(64) DEFAULT 'vpnuser'"),
                ("config_text",              "TEXT"),
                ("config_qr",               "TEXT"),
                ("split_tunnel_enabled",     "BOOLEAN DEFAULT 1"),
                ("setup_status",             "VARCHAR(20)"),
                ("setup_step",               "VARCHAR(50)"),
                ("setup_log",               "TEXT"),
                ("setup_error",             "TEXT"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in existing:
                    conn.execute(sa.text(f"ALTER TABLE connections ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"Migration: added column connections.{col_name}")
            conn.commit()

            # Migrate servers table
            result2 = conn.execute(sa.text("PRAGMA table_info(servers)"))
            srv_cols = {row[1] for row in result2.fetchall()}
            srv_new_cols = [
                ("awg_installed", "BOOLEAN DEFAULT 0"),
            ]
            for col_name, col_type in srv_new_cols:
                if col_name not in srv_cols:
                    conn.execute(sa.text(f"ALTER TABLE servers ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"Migration: added column servers.{col_name}")
            conn.commit()
    except Exception as e:
        logger.warning(f"Migration warning (non-fatal): {e}")


def create_tables():
    from app.db.database import Base, engine
    import app.models.server       # noqa: F401
    import app.models.connection   # noqa: F401
    import app.models.admin_user   # noqa: F401
    import app.models.session      # noqa: F401  ← ActiveSession
    import app.models.domain       # noqa: F401  ← Domain, Subdomain
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
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
