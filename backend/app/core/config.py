from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    DATABASE_URL: str = "sqlite:///./vpn_admin.db"

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme123"

    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080", "http://localhost", "*"]

    # SSH defaults
    SSH_CONNECT_TIMEOUT: int = 30
    SSH_COMMAND_TIMEOUT: int = 120

    # Port range for auto-assignment
    PORT_RANGE_START: int = 10000
    PORT_RANGE_END: int = 65000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
