"""Phase 9 occupancy projection API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import (
    IdentityDecision,
    IdentityReviewStatus,
    JourneyCorrelationDecision,
    OccupancyFactType,
    OccupancySessionState,
    OccupancySubjectType,
)


class OccupancySessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journey_id: UUID
    zone_id: UUID
    subject_type: OccupancySubjectType
    person_id: UUID | None
    external_subject_key: str | None
    entry_journey_event_id: UUID
    exit_journey_event_id: UUID | None
    last_journey_event_id: UUID
    last_camera_id: UUID
    state: OccupancySessionState
    identity_decision: IdentityDecision
    identification_confidence: float
    review_status: IdentityReviewStatus
    entered_at: datetime
    exited_at: datetime | None
    last_seen_at: datetime
    state_reason: str
    reconstruction_version: int


class OccupancyFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journey_id: UUID
    journey_event_id: UUID
    camera_id: UUID
    origin_zone_id: UUID | None
    destination_zone_id: UUID | None
    current_zone_id: UUID | None
    fact_type: OccupancyFactType
    subject_type: OccupancySubjectType
    person_id: UUID | None
    external_subject_key: str | None
    identity_decision: IdentityDecision
    identity_confidence: float
    correlation_decision: JourneyCorrelationDecision
    correlation_score: float
    occurred_at: datetime
    fact_metadata: dict[str, Any]


class OccupancySummaryResponse(BaseModel):
    active_total: int
    active_employee: int
    active_unknown: int
    active_unresolved: int
    temporarily_lost: int
    stale: int
    needs_review: int
    active_count_definition: str = "state=ACTIVE only"


class OccupancyConfigurationResponse(BaseModel):
    event_time_reconstruction: bool = True
    camera_offline_closes_session: bool = False
    midnight_closes_structured_session: bool = False
    active_state: str = "ACTIVE"
    next_phase: str = "policy-engine"
