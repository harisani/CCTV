from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from app.api.dependencies import get_statistics_repository
from app.api.schemas import StatisticsResponse
from app.api.security import require_authenticated_user
from app.repository import StatisticsRepository

router = APIRouter(prefix="/statistics", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=StatisticsResponse)
async def get_statistics(
    camera_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    repository: StatisticsRepository = Depends(get_statistics_repository),
) -> StatisticsResponse:
    if start_at is None:
        start_at = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return StatisticsResponse(**await repository.summary(camera_id=camera_id, start_at=start_at, end_at=end_at))
