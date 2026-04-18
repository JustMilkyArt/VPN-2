from fastapi import APIRouter
from .auth import router as auth_router
from .servers import router as servers_router
from .connections import router as connections_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(servers_router)
api_router.include_router(connections_router)
