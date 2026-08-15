"""Health check endpoint used by load balancers and uptime probes."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.config import settings
from app.shared.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/health", tags=["Health"])


class HealthStatus(BaseModel):
    """Payload describing the current service state."""

    status: str
    environment: str
    version: str


@router.get(
    "",
    response_model=APIResponse[HealthStatus],
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Returns the liveness state of the API.",
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
