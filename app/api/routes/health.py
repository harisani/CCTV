from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_app_settings,
    get_database_session,
    get_health_service,
)
from app.config.settings import Settings
from app.services.health_service import HealthService

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str


class LiveResponse(BaseModel):
    status: str


@router.get("/health/live", response_model=LiveResponse)
async def health_live() -> LiveResponse:
    """Report that the HTTP process can serve requests."""
    return LiveResponse(status="ok")


@router.get("/health/ready", response_model=LiveResponse)
async def health_ready(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
    health_service: HealthService = Depends(get_health_service),
) -> LiveResponse:
    """Report whether startup completed and PostgreSQL is reachable."""
    if not request.app.state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application is not ready",
        )
    if not await health_service.database_ready(session, settings.health_database_timeout_seconds):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    return LiveResponse(status="ok")


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Preserve the legacy database-backed health response."""
    if not await health_service.database_ready(session, settings.health_database_timeout_seconds):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    return HealthResponse(status="ok", environment=settings.app_env, database="connected")
