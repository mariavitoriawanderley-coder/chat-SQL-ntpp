"""Agrega os routers da v1.

Cada fase do roadmap acrescenta um router aqui — chat (Fase 2),
query (Fase 3).
"""

from fastapi import APIRouter

from app.api.v1 import catalog, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(catalog.router)
