"""API contracts for durable asynchronous AI processing jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import AIJobStatus, AIJobType, ProcessingPriority


class AIProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_event_id: UUID
    job_type: AIJobType
    status: AIJobStatus
    priority: ProcessingPriority
    attempt_count: int
    max_attempts: int
    available_at: datetime
    locked_at: datetime | None
    lock_expires_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class AIProcessingJobDetailResponse(AIProcessingJobResponse):
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    last_error_message: str | None


class AIQueueStatisticsResponse(BaseModel):
    counts: dict[str, int]
    backlog: int
    processing: int
    failed: int
    oldest_available_at: datetime | None
    oldest_age_seconds: float | None
    average_processing_latency_ms: float | None
    warning_threshold: int
    queue_health: str
