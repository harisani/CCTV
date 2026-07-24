"""Public Phase 7 metadata contracts; embedding vectors remain private."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import PPEAnalysisStatus


class BodyCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    body_asset_id: UUID
    sequence_index: int
    bbox: dict[str, float] | None
    detector_confidence: float | None
    quality_score: float
    quality_metrics: dict[str, Any]
    selected: bool
    rejection_reason: str | None
    captured_at: datetime


class BodyEmbeddingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body_candidate_id: UUID
    person_id: UUID | None
    model_version_id: UUID
    quality_score: float
    source: str
    active: bool
    captured_at: datetime
    expires_at: datetime | None


class PPEAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    body_candidate_id: UUID | None
    model_version_id: UUID | None
    status: PPEAnalysisStatus
    detections: list[dict[str, Any]]
    observed_items: dict[str, Any]
    color_observation: dict[str, Any] | None
    confidence_score: float
    reasoning_metadata: dict[str, Any]
    needs_review: bool
    analyzed_at: datetime


class BodyAnalysisConfigurationResponse(BaseModel):
    realtime_reid_enabled: bool
    body_similarity_threshold: float
    body_ambiguity_margin: float
    body_minimum_quality: float
    body_embedding_retention_days: int
    ppe_analysis_enabled: bool
    ppe_model_configured: bool
    ppe_confidence_threshold: float
    ppe_policy_evaluation_phase: int = 10
