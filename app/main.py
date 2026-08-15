"""Application entrypoint: builds and exposes the FastAPI instance."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.exceptions import register_exception_handlers
from app.shared.schemas.response import APIResponse, success_response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown hooks.

    Cache and background worker wiring is attached here as those layers land
    in later commits.
    """
    settings.ensure_storage_dirs()
    yield
    await dispose_engine()


def create_application() -> FastAPI:
    """Application factory, keeps startup testable and import-order safe."""
    application = FastAPI(
        title=settings.project_name,
        description=settings.description,
        version=settings.version,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    return application


app = create_application()


@app.get("/", tags=["Root"], response_model=APIResponse[dict], include_in_schema=False)
async def root() -> APIResponse[dict]:
    """Entry point pointing clients at the docs and the versioned API."""
    return success_response(
        data={
            "name": settings.project_name,
            "version": settings.version,
            "docs": settings.docs_url,
            "api": settings.api_v1_prefix,
        },
        message=f"{settings.project_name} is running",
    )
