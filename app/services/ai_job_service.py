"""Use cases for observing and administrating durable AI jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.models import (
    AIJobStatus,
    AIJobType,
    AIProcessingJob,
    ProcessingPriority,
)
from app.repository import AIJobRepository


class AIJobService:
    def __init__(
        self,
        repository: AIJobRepository,
        *,
        backlog_warning_threshold: int,
    ) -> None:
        self._repository = repository
        self._backlog_warning_threshold = backlog_warning_threshold

    async def list_jobs(
        self,
        *,
        status: AIJobStatus | None,
        job_type: AIJobType | None,
        priority: ProcessingPriority | None,
        capture_event_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AIProcessingJob], int]:
        return await self._repository.list_filtered(
            status=status,
            job_type=job_type,
            priority=priority,
            capture_event_id=capture_event_id,
            offset=offset,
            limit=limit,
        )

    async def get(self, job_id: UUID) -> AIProcessingJob | None:
        return await self._repository.get(job_id)

    async def statistics(self) -> dict[str, object]:
        statistics = await self._repository.statistics(
            now=datetime.now(UTC)
        )
        statistics["warning_threshold"] = self._backlog_warning_threshold
        statistics["queue_health"] = (
            "WARNING"
            if statistics["backlog"] >= self._backlog_warning_threshold
            else "HEALTHY"
        )
        return statistics

    async def cancel(self, job_id: UUID) -> AIProcessingJob | None:
        job = await self._repository.cancel(job_id, now=datetime.now(UTC))
        if job is not None:
            await self._repository.commit()
        return job

    async def retry(self, job_id: UUID) -> AIProcessingJob | None:
        job = await self._repository.retry_failed(
            job_id, now=datetime.now(UTC)
        )
        if job is not None:
            await self._repository.commit()
        return job
