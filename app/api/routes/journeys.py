"""Authenticated Phase 8 global journey read API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_app_settings,
    get_journey_correlation_service,
)
from app.api.journey_schemas import (
    GlobalJourneyResponse,
    JourneyConfigurationResponse,
    JourneyCorrelationResponse,
    JourneyEventResponse,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user
from app.config.settings import Settings
from app.models import JourneyCorrelationDecision, JourneyStatus
from app.services.journey_correlation_service import (
    JourneyCorrelationService,
)

router = APIRouter(
    prefix="/global-journeys",
    dependencies=[Depends(require_authenticated_user)],
)


@router.get(
    "/configuration", response_model=JourneyConfigurationResponse
)
async def journey_configuration(
    settings: Settings = Depends(get_app_settings),
) -> JourneyConfigurationResponse:
    return JourneyConfigurationResponse(
        match_threshold=settings.journey_match_threshold,
        unknown_match_threshold=(
            settings.journey_unknown_match_threshold
        ),
        ambiguity_margin=settings.journey_ambiguity_margin,
        maximum_gap_seconds=settings.journey_max_gap_seconds,
        minimum_body_similarity=settings.journey_min_body_similarity,
    )


@router.get("", response_model=Page[GlobalJourneyResponse])
async def list_global_journeys(
    person_id: UUID | None = None,
    zone_id: UUID | None = None,
    camera_id: UUID | None = None,
    journey_status: JourneyStatus | None = Query(
        default=None, alias="status"
    ),
    needs_review: bool | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: JourneyCorrelationService = Depends(
        get_journey_correlation_service
    ),
) -> Page[GlobalJourneyResponse]:
    if start_at and end_at and start_at > end_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_at must not be after end_at",
        )
    items, total = await service.list_journeys(
        person_id=person_id,
        zone_id=zone_id,
        camera_id=camera_id,
        status=journey_status,
        needs_review=needs_review,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
    )
    return Page[GlobalJourneyResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get(
    "/correlations", response_model=Page[JourneyCorrelationResponse]
)
async def list_journey_correlations(
    journey_id: UUID | None = None,
    capture_id: UUID | None = None,
    decision: JourneyCorrelationDecision | None = None,
    impossible_travel: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: JourneyCorrelationService = Depends(
        get_journey_correlation_service
    ),
) -> Page[JourneyCorrelationResponse]:
    items, total = await service.list_correlations(
        journey_id=journey_id,
        capture_id=capture_id,
        decision=decision,
        impossible_travel=impossible_travel,
        offset=offset,
        limit=limit,
    )
    return Page[JourneyCorrelationResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get("/{journey_id}", response_model=GlobalJourneyResponse)
async def get_global_journey(
    journey_id: UUID,
    service: JourneyCorrelationService = Depends(
        get_journey_correlation_service
    ),
) -> GlobalJourneyResponse:
    journey = await service.get_journey(journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    return GlobalJourneyResponse.model_validate(journey)


@router.get(
    "/{journey_id}/events",
    response_model=Page[JourneyEventResponse],
)
async def list_journey_events(
    journey_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: JourneyCorrelationService = Depends(
        get_journey_correlation_service
    ),
) -> Page[JourneyEventResponse]:
    journey = await service.get_journey(journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    items, total = await service.list_events(
        journey_id=journey_id,
        offset=offset,
        limit=limit,
    )
    return Page[JourneyEventResponse](
        items=items, total=total, offset=offset, limit=limit
    )
