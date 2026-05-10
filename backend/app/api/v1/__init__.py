from fastapi import APIRouter
from .auth import router as auth_router
from .servers import router as servers_router
from .connections import router as connections_router
from .users import router as users_router
from .domains import router as domains_router
from .subscribe import router as subscribe_router
from .client import router as client_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(servers_router)
api_router.include_router(connections_router)
api_router.include_router(users_router)
api_router.include_router(domains_router)
api_router.include_router(subscribe_router)
api_router.include_router(client_router)
