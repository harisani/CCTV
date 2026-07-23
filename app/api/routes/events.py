from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_event_repository
from app.api.schemas import EventResponse, Page
from app.api.security import require_authenticated_user
from app.repository import EventRepository

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
) -> Page[EventResponse]:
    items, total = await repository.list_filtered(
        camera_id=camera_id,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
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
            snapshot_id=snapshot_id,
            camera_id=event_camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
        )
        for (
            event,
            snapshot_id,
            event_camera_id,
            camera_name,
            camera_location,
            byte_track_id,
        ) in items
    ]
    return Page[EventResponse](
        items=responses,
        total=total,
        offset=offset,
        limit=limit,
    )
