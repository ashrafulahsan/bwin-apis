"""Aggregates every v1 router into a single mount point."""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()

api_router.include_router(health.router)
