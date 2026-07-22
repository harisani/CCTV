from datetime import UTC, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from app.api.dependencies import get_services, get_statistics_repository
from app.api.schemas import StatisticsResponse
from app.api.security import require_authenticated_user
from app.repository import StatisticsRepository
from app.services.container import ServiceContainer

router = APIRouter(prefix="/statistics", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=StatisticsResponse)
async def get_statistics(
    camera_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    repository: StatisticsRepository = Depends(get_statistics_repository),
    services: ServiceContainer = Depends(get_services),
) -> StatisticsResponse:
    if start_at is None:
        local_timezone = ZoneInfo(services.settings.presence_timezone)
        start_at = datetime.combine(
            datetime.now(local_timezone).date(),
            time.min,
            tzinfo=local_timezone,
        ).astimezone(UTC)
    summary = await repository.summary(camera_id=camera_id, start_at=start_at, end_at=end_at)
    visible_count = await services.live_visibility.total(camera_id)
    summary["current_person_count"] = visible_count
    summary["confirmed_person_count"] = visible_count
    return StatisticsResponse(**summary)
