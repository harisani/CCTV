"""Authenticated history of local tracks and zone transitions."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_zone_transition_service
from app.api.schemas import Page
from app.api.security import require_authenticated_user
from app.api.zone_transition_schemas import (
    LocalTrackResponse,
    ZoneEventResponse,
)
from app.models import ZoneEventType
from app.services.zone_transition_service import ZoneTransitionService

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


@router.get("/zone-events", response_model=Page[ZoneEventResponse])
async def list_zone_events(
    camera_id: UUID | None = None,
    zone_id: UUID | None = None,
    tracking_id: UUID | None = None,
    event_type: ZoneEventType | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ZoneTransitionService = Depends(get_zone_transition_service),
) -> Page[ZoneEventResponse]:
    try:
        items, total = await service.list_events(
            camera_id=camera_id,
            zone_id=zone_id,
            tracking_id=tracking_id,
            event_type=event_type,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Page[ZoneEventResponse](
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/zone-events/{event_id}",
    response_model=ZoneEventResponse,
)
async def get_zone_event(
    event_id: UUID,
    service: ZoneTransitionService = Depends(get_zone_transition_service),
) -> ZoneEventResponse:
    event = await service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Zone event not found")
    return ZoneEventResponse.model_validate(event)


@router.get("/local-tracks", response_model=Page[LocalTrackResponse])
async def list_local_tracks(
    camera_id: UUID | None = None,
    person_id: UUID | None = None,
    active: bool | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ZoneTransitionService = Depends(get_zone_transition_service),
) -> Page[LocalTrackResponse]:
    try:
        items, total = await service.list_tracks(
            camera_id=camera_id,
            person_id=person_id,
            active=active,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Page[LocalTrackResponse](
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )
