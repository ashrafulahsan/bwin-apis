"""Health endpoints used by load balancers, orchestrators and uptime probes."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import check_database_connection
from app.core.exceptions import ServiceUnavailableException
from app.shared.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/health", tags=["Health"])


class HealthStatus(BaseModel):
    """Payload describing the current service state."""

    status: str
    environment: str
    version: str


class ReadinessStatus(HealthStatus):
    """Health payload plus the state of each backing service."""

    database: str


@router.get(
    "",
    response_model=APIResponse[HealthStatus],
    status_code=status.HTTP_200_OK,
    summary="Liveness check",
    description="Returns the liveness state of the API without touching dependencies.",
)
async def health_check() -> APIResponse[HealthStatus]:
    return success_response(
        data=HealthStatus(
            status="ok",
            environment=settings.environment.value,
            version=settings.version,
        ),
        message="Service is healthy",
    )


@router.get(
    "/ready",
    response_model=APIResponse[ReadinessStatus],
    status_code=status.HTTP_200_OK,
    summary="Readiness check",
    description="Verifies the API can reach PostgreSQL before accepting traffic.",
)
async def readiness_check() -> APIResponse[ReadinessStatus]:
    if not await check_database_connection():
        raise ServiceUnavailableException("Database is unreachable.")

    return success_response(
        data=ReadinessStatus(
            status="ok",
            environment=settings.environment.value,
            version=settings.version,
            database="connected",
        ),
        message="Service is ready",
    )
