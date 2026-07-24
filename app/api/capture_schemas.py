"""Public API contracts for capture envelopes and evidence assets."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import (
    CaptureEventStatus,
    EvidenceAssetType,
    EvidenceIntegrityStatus,
)


class EvidenceAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    asset_type: EvidenceAssetType
    sequence_index: int
    checksum_sha256: str | None
    integrity_status: EvidenceIntegrityStatus
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    is_primary: bool
    captured_at: datetime
    retention_until: datetime | None
    deleted_at: datetime | None


class CaptureEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_event_id: UUID | None
    camera_id: UUID
    zone_id: UUID | None
    virtual_line_id: UUID | None
    tracking_id: UUID | None
    status: CaptureEventStatus
    direction: str | None
    bbox: dict[str, float] | None
    centroid: dict[str, float] | None
    capture_quality: dict[str, Any] | None
    captured_at: datetime
    processing_started_at: datetime | None
    processed_at: datetime | None
    failed_at: datetime | None
    attempt_count: int


class CaptureEventDetailResponse(CaptureEventResponse):
    capture_metadata: dict[str, Any] | None
    evidence_assets: list[EvidenceAssetResponse]


class EvidenceIntegrityResponse(BaseModel):
    asset: EvidenceAssetResponse
    actual_checksum_sha256: str | None
    actual_size_bytes: int | None
