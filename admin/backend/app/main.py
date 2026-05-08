"""
VPN Infrastructure Management System - FastAPI Backend
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.init_db import init_db
from app.api.v1 import api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting VPN Admin Backend...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="VPN Infrastructure Manager",
    description="Centralized VPN infrastructure management system with auto-deployment",
    version="1.0.0-MVP",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(api_router)


@app.get("/", tags=["health"])
def root():
    return {
        "service": "VPN Infrastructure Manager",
        "version": "1.0.0-MVP",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}
