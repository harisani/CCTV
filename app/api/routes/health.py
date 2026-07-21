from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database_session
from app.config.settings import Settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> HealthResponse:
    """Return liveness only after confirming PostgreSQL is reachable."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    return HealthResponse(status="ok", environment=settings.app_env, database="connected")
