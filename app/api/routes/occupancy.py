"""Authenticated structured occupancy history and summary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_occupancy_service
from app.api.occupancy_schemas import (
    OccupancyConfigurationResponse,
    OccupancyFactResponse,
    OccupancySessionResponse,
    OccupancySummaryResponse,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user
from app.models import OccupancySessionState, OccupancySubjectType
from app.services.occupancy_service import OccupancyService

router = APIRouter(
    prefix="/occupancy",
    dependencies=[Depends(require_authenticated_user)],
)


@router.get(
    "/configuration", response_model=OccupancyConfigurationResponse
)
async def occupancy_configuration() -> OccupancyConfigurationResponse:
    return OccupancyConfigurationResponse()


@router.get("/summary", response_model=OccupancySummaryResponse)
async def occupancy_summary(
    zone_id: UUID | None = None,
    service: OccupancyService = Depends(get_occupancy_service),
) -> OccupancySummaryResponse:
    return OccupancySummaryResponse(
        **await service.summary(zone_id)
    )


@router.get(
    "/sessions", response_model=Page[OccupancySessionResponse]
)
async def list_occupancy_sessions(
    zone_id: UUID | None = None,
    journey_id: UUID | None = None,
    person_id: UUID | None = None,
    session_state: OccupancySessionState | None = Query(
        default=None, alias="state"
    ),
    subject_type: OccupancySubjectType | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: OccupancyService = Depends(get_occupancy_service),
) -> Page[OccupancySessionResponse]:
    if start_at and end_at and start_at > end_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_at must not be after end_at",
        )
    items, total = await service.list_sessions(
        zone_id=zone_id,
        journey_id=journey_id,
        person_id=person_id,
        state=session_state,
        subject_type=subject_type,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
    )
    return Page[OccupancySessionResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get("/facts", response_model=Page[OccupancyFactResponse])
async def list_occupancy_facts(
    journey_id: UUID | None = None,
    zone_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: OccupancyService = Depends(get_occupancy_service),
) -> Page[OccupancyFactResponse]:
    items, total = await service.list_facts(
        journey_id=journey_id,
        zone_id=zone_id,
        offset=offset,
        limit=limit,
    )
    return Page[OccupancyFactResponse](
        items=items, total=total, offset=offset, limit=limit
    )
