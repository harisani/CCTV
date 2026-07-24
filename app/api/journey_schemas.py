"""Public contracts for global journeys and correlation evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import (
    IdentityDecision,
    IdentityReviewStatus,
    JourneyCorrelationDecision,
    JourneyEventType,
    JourneyStatus,
)


class GlobalJourneyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journey_key: str
    identity_person_id: UUID | None
    identity_external_subject_key: str | None
    identity_decision: IdentityDecision
    identity_confidence: float
    first_seen_at: datetime
    last_seen_at: datetime
    current_zone_id: UUID | None
    last_camera_id: UUID | None
    last_event_id: UUID | None
    status: JourneyStatus
    review_status: IdentityReviewStatus
    event_count: int
    version: int


class JourneyEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journey_id: UUID
    capture_event_id: UUID
    tracking_id: UUID | None
    camera_id: UUID
    origin_zone_id: UUID | None
    destination_zone_id: UUID | None
    current_zone_id: UUID | None
    event_type: JourneyEventType
    identity_person_id: UUID | None
    identity_external_subject_key: str | None
    identity_decision: IdentityDecision
    identity_confidence: float
    occurred_at: datetime
    evidence_metadata: dict[str, Any]


class JourneyCorrelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    journey_id: UUID
    journey_event_id: UUID
    anchor_journey_event_id: UUID | None
    decision: JourneyCorrelationDecision
    correlation_score: float
    second_best_score: float | None
    identity_score: float
    topology_score: float
    time_score: float
    appearance_score: float
    candidate_count: int
    impossible_travel: bool
    reasoning_metadata: dict[str, Any]
    correlated_at: datetime


class JourneyConfigurationResponse(BaseModel):
    match_threshold: float
    unknown_match_threshold: float
    ambiguity_margin: float
    maximum_gap_seconds: float
    minimum_body_similarity: float
    event_time_correlation: bool = True
    impossible_travel_alert_phase: int = 10
