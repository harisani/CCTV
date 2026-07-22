from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from app.api.dependencies import get_app_settings, get_event_repository
from app.api.schemas import EventResponse, Page
from app.api.security import require_authenticated_user
from app.repository import EventRepository
from app.config.settings import Settings

router = APIRouter(prefix="/events", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[EventResponse])
async def list_events(
    camera_id: UUID | None = None,
    event_type: str | None = Query(default=None, pattern="^(ENTER|EXIT)$"),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: EventRepository = Depends(get_event_repository),
    settings: Settings = Depends(get_app_settings),
) -> Page[EventResponse]:
    items, total = await repository.list_filtered(
        camera_id=camera_id, event_type=event_type, start_at=start_at, end_at=end_at, offset=offset, limit=limit
    )
    responses = [
        EventResponse(
            id=event.id,
            tracking_id=event.tracking_id,
            byte_track_id=byte_track_id,
            event_type=event.event_type.value,
            line_id=event.line_id,
            centroid=event.centroid,
            occurred_at=event.occurred_at,
            snapshot_url=_snapshot_url(image_path, settings),
            camera_id=camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
        )
        for event, image_path, camera_id, camera_name, camera_location, byte_track_id in items
    ]
    return Page[EventResponse](items=responses, total=total, offset=offset, limit=limit)


def _snapshot_url(image_path: str | None, settings: Settings) -> str | None:
    if image_path is None:
        return None
    path = Path(image_path)
    try:
        return f"/storage/{path.relative_to(settings.storage_path).as_posix()}"
    except ValueError:
        return f"/storage/{path.name}"
