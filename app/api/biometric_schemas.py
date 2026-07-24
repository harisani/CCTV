"""Safe API contracts for biometric candidates and identity decisions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    BiometricModality,
    IdentityDecision,
    IdentityReviewStatus,
)


class FaceCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    face_asset_id: UUID | None
    periocular_asset_id: UUID | None
    sequence_index: int
    bbox: dict[str, float]
    landmarks: list[dict[str, float]] | None
    detection_confidence: float
    quality_score: float
    quality_metrics: dict[str, object]
    selected: bool
    rejection_reason: str | None
    captured_at: datetime


class IdentityMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    face_candidate_id: UUID | None
    body_candidate_id: UUID | None
    matched_template_id: UUID | None
    matched_body_embedding_id: UUID | None
    candidate_person_id: UUID | None
    candidate_external_subject_key: str | None
    modality: BiometricModality
    decision: IdentityDecision
    similarity_score: float | None
    confidence_score: float
    second_best_similarity: float | None
    reasoning_metadata: dict[str, object]
    review_status: IdentityReviewStatus
    matched_at: datetime


class BiometricTemplateResponse(BaseModel):
    """Template metadata only; embedding is deliberately excluded."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_id: UUID | None
    external_subject_key: str | None
    source_asset_id: UUID | None
    model_version_id: UUID
    modality: BiometricModality
    native_dimension: int
    quality_score: float
    active: bool
    enrolled_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class BiometricEnrollmentRequest(BaseModel):
    source_asset_id: UUID
    person_id: UUID | None = None
    external_subject_key: str | None = Field(
        default=None, min_length=1, max_length=160
    )

    @model_validator(mode="after")
    def validate_subject(self) -> "BiometricEnrollmentRequest":
        if self.person_id is None and not (
            self.external_subject_key
            and self.external_subject_key.strip()
        ):
            raise ValueError(
                "person_id or external_subject_key must be provided"
            )
        return self
