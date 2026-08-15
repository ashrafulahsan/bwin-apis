"""Aggregates every v1 router into a single mount point."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.translations.routers import router as translations_router

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(translations_router)
