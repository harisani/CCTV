"""Public contracts for local tracking and zone transition history."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import ZoneEventType


class LocalTrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    camera_id: UUID
    person_id: UUID | None
    byte_track_id: int
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None
    last_centroid: dict[str, float] | None
    last_bbox: dict[str, float] | None
    detector_confidence: float | None
    direction: str | None
    detector_model: str | None
    is_active: bool


class ZoneEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transition_id: UUID
    crossing_event_id: UUID | None
    tracking_id: UUID | None
    camera_id: UUID
    virtual_line_id: UUID | None
    zone_id: UUID
    origin_zone_id: UUID | None
    destination_zone_id: UUID | None
    event_type: ZoneEventType
    local_track_id: int
    direction: str | None
    centroid: dict[str, float]
    confidence: float | None
    occurred_at: datetime
    event_metadata: dict[str, Any] | None
    created_at: datetime
