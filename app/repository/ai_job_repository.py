"""PostgreSQL-backed durable queue for asynchronous AI processing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIJobStatus,
    AIJobType,
    AIProcessingJob,
    CaptureEvent,
    CaptureEventStatus,
    ProcessingPriority,
)
from app.repository.base import BaseRepository

TERMINAL_JOB_STATUSES = {
    AIJobStatus.COMPLETED,
    AIJobStatus.FAILED,
    AIJobStatus.CANCELLED,
}


class AIJobRepository(BaseRepository[AIProcessingJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AIProcessingJob)

    async def enqueue(
        self,
        *,
        capture_event: CaptureEvent,
        job_type: AIJobType,
        priority: ProcessingPriority,
        idempotency_key: str,
        payload: dict[str, Any] | None,
        max_attempts: int,
        available_at: datetime,
    ) -> tuple[AIProcessingJob, bool]:
        existing = await self.session.scalar(
            select(AIProcessingJob).where(
                AIProcessingJob.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing, False
        job = AIProcessingJob(
            id=uuid4(),
            capture_event_id=capture_event.id,
            job_type=job_type,
            status=AIJobStatus.QUEUED,
            priority=priority,
            idempotency_key=idempotency_key,
            payload=payload,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=available_at,
            created_at=available_at,
            updated_at=available_at,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(job)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(AIProcessingJob).where(
                    AIProcessingJob.idempotency_key == idempotency_key
                )
            )
            if existing is None:
                raise
            return existing, False
        capture_event.status = CaptureEventStatus.QUEUED
        capture_event.failure_reason = None
        capture_event.updated_at = available_at
        await self.session.flush()
        return job, True

    async def recover_expired_leases(
        self,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        jobs = list(
            (
                await self.session.scalars(
                    select(AIProcessingJob)
                    .where(
                        AIProcessingJob.status == AIJobStatus.PROCESSING,
                        AIProcessingJob.lock_expires_at.is_not(None),
                        AIProcessingJob.lock_expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        retried = 0
        failed = 0
        for job in jobs:
            capture = await self.session.get(CaptureEvent, job.capture_event_id)
            exhausted = job.attempt_count >= job.max_attempts
            job.status = (
                AIJobStatus.FAILED if exhausted else AIJobStatus.RETRYING
            )
            job.available_at = now
            job.failed_at = now if exhausted else None
            job.last_error_code = "LEASE_EXPIRED"
            job.last_error_message = "Worker lease expired before completion"
            self._release_lock(job)
            job.updated_at = now
            if capture is not None:
                capture.status = (
                    CaptureEventStatus.FAILED
                    if exhausted
                    else CaptureEventStatus.RETRYING
                )
                capture.retry_count = max(0, job.attempt_count - 1)
                capture.failure_reason = job.last_error_message
                capture.failed_at = now if exhausted else None
                capture.updated_at = now
            if exhausted:
                failed += 1
            else:
                retried += 1
        await self.session.flush()
        return retried, failed

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: float,
    ) -> AIProcessingJob | None:
        priority_order = case(
            (AIProcessingJob.priority == ProcessingPriority.HIGH, 0),
            (AIProcessingJob.priority == ProcessingPriority.NORMAL, 1),
            else_=2,
        )
        job = await self.session.scalar(
            select(AIProcessingJob)
            .where(
                AIProcessingJob.status.in_(
                    (AIJobStatus.QUEUED, AIJobStatus.RETRYING)
                ),
                AIProcessingJob.available_at <= now,
                AIProcessingJob.attempt_count < AIProcessingJob.max_attempts,
            )
            .order_by(
                priority_order,
                AIProcessingJob.available_at,
                AIProcessingJob.created_at,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = AIJobStatus.PROCESSING
        job.attempt_count += 1
        job.locked_by = worker_id
        job.locked_at = now
        job.lock_expires_at = now + timedelta(seconds=lease_seconds)
        job.last_heartbeat_at = now
        job.started_at = job.started_at or now
        job.updated_at = now
        capture = await self.session.get(CaptureEvent, job.capture_event_id)
        if capture is not None:
            capture.status = CaptureEventStatus.PROCESSING
            capture.processing_started_at = capture.processing_started_at or now
            capture.attempt_count = job.attempt_count
            capture.retry_count = max(0, job.attempt_count - 1)
            capture.failure_reason = None
            capture.updated_at = now
        await self.session.flush()
        return job

    async def heartbeat(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: float,
    ) -> bool:
        job = await self.session.scalar(
            select(AIProcessingJob)
            .where(
                AIProcessingJob.id == job_id,
                AIProcessingJob.status == AIJobStatus.PROCESSING,
                AIProcessingJob.locked_by == worker_id,
            )
            .with_for_update()
        )
        if job is None:
            return False
        job.last_heartbeat_at = now
        job.lock_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        await self.session.flush()
        return True

    async def complete(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        result: dict[str, Any] | None,
        now: datetime,
    ) -> bool:
        job = await self._locked_processing_job(job_id, worker_id, now)
        if job is None:
            return False
        job.status = AIJobStatus.COMPLETED
        job.result = result
        job.completed_at = now
        job.failed_at = None
        job.last_error_code = None
        job.last_error_message = None
        self._release_lock(job)
        job.updated_at = now
        capture = await self.session.get(CaptureEvent, job.capture_event_id)
        if capture is not None:
            capture.status = CaptureEventStatus.COMPLETED
            capture.processed_at = now
            capture.failed_at = None
            capture.failure_reason = None
            capture.processing_latency_ms = max(
                0,
                round((now - capture.captured_at).total_seconds() * 1000),
            )
            capture.dashboard_updated_at = now
            capture.updated_at = now
        await self.session.flush()
        return True

    async def fail(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: float,
        retryable: bool,
        now: datetime,
    ) -> AIJobStatus | None:
        job = await self._locked_processing_job(job_id, worker_id, now)
        if job is None:
            return None
        exhausted = not retryable or job.attempt_count >= job.max_attempts
        job.status = AIJobStatus.FAILED if exhausted else AIJobStatus.RETRYING
        job.available_at = now + timedelta(seconds=retry_delay_seconds)
        job.failed_at = now if exhausted else None
        job.last_error_code = error_code
        job.last_error_message = error_message
        self._release_lock(job)
        job.updated_at = now
        capture = await self.session.get(CaptureEvent, job.capture_event_id)
        if capture is not None:
            capture.status = (
                CaptureEventStatus.FAILED
                if exhausted
                else CaptureEventStatus.RETRYING
            )
            capture.retry_count = max(0, job.attempt_count - 1)
            capture.failure_reason = error_message
            capture.failed_at = now if exhausted else None
            capture.dashboard_updated_at = now
            capture.updated_at = now
        await self.session.flush()
        return job.status

    async def cancel(
        self,
        job_id: UUID,
        *,
        now: datetime,
    ) -> AIProcessingJob | None:
        job = await self.session.scalar(
            select(AIProcessingJob)
            .where(AIProcessingJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            return None
        if job.status in TERMINAL_JOB_STATUSES:
            raise ValueError(
                "Completed, failed, or cancelled jobs cannot be cancelled"
            )
        job.status = AIJobStatus.CANCELLED
        job.cancelled_at = now
        self._release_lock(job)
        job.updated_at = now
        capture = await self.session.get(CaptureEvent, job.capture_event_id)
        if capture is not None:
            capture.status = CaptureEventStatus.CANCELLED
            capture.dashboard_updated_at = now
            capture.updated_at = now
        await self.session.flush()
        return job

    async def retry_failed(
        self,
        job_id: UUID,
        *,
        now: datetime,
    ) -> AIProcessingJob | None:
        job = await self.session.scalar(
            select(AIProcessingJob)
            .where(AIProcessingJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            return None
        if job.status not in {AIJobStatus.FAILED, AIJobStatus.CANCELLED}:
            raise ValueError("Only failed or cancelled jobs can be retried")
        job.status = AIJobStatus.RETRYING
        job.attempt_count = 0
        job.available_at = now
        job.failed_at = None
        job.cancelled_at = None
        job.last_error_code = None
        job.last_error_message = None
        self._release_lock(job)
        job.updated_at = now
        capture = await self.session.get(CaptureEvent, job.capture_event_id)
        if capture is not None:
            capture.status = CaptureEventStatus.RETRYING
            capture.failed_at = None
            capture.failure_reason = None
            capture.dashboard_updated_at = now
            capture.updated_at = now
        await self.session.flush()
        return job

    async def list_filtered(
        self,
        *,
        status: AIJobStatus | None,
        job_type: AIJobType | None,
        priority: ProcessingPriority | None,
        capture_event_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AIProcessingJob], int]:
        filters = []
        if status is not None:
            filters.append(AIProcessingJob.status == status)
        if job_type is not None:
            filters.append(AIProcessingJob.job_type == job_type)
        if priority is not None:
            filters.append(AIProcessingJob.priority == priority)
        if capture_event_id is not None:
            filters.append(
                AIProcessingJob.capture_event_id == capture_event_id
            )
        statement = select(AIProcessingJob).where(*filters)
        jobs = list(
            (
                await self.session.scalars(
                    statement.order_by(AIProcessingJob.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return jobs, int(total or 0)

    async def statistics(self, *, now: datetime) -> dict[str, Any]:
        rows = (
            await self.session.execute(
                select(AIProcessingJob.status, func.count())
                .group_by(AIProcessingJob.status)
            )
        ).all()
        counts = {status.value: int(count) for status, count in rows}
        oldest = await self.session.scalar(
            select(func.min(AIProcessingJob.available_at)).where(
                AIProcessingJob.status.in_(
                    (AIJobStatus.QUEUED, AIJobStatus.RETRYING)
                )
            )
        )
        average_latency = await self.session.scalar(
            select(func.avg(CaptureEvent.processing_latency_ms)).where(
                CaptureEvent.processing_latency_ms.is_not(None)
            )
        )
        return {
            "counts": counts,
            "backlog": counts.get(AIJobStatus.QUEUED.value, 0)
            + counts.get(AIJobStatus.RETRYING.value, 0),
            "processing": counts.get(AIJobStatus.PROCESSING.value, 0),
            "failed": counts.get(AIJobStatus.FAILED.value, 0),
            "oldest_available_at": oldest,
            "oldest_age_seconds": (
                max(0.0, (now - oldest).total_seconds())
                if oldest is not None
                else None
            ),
            "average_processing_latency_ms": (
                float(average_latency)
                if average_latency is not None
                else None
            ),
        }

    async def _locked_processing_job(
        self,
        job_id: UUID,
        worker_id: str,
        now: datetime,
    ) -> AIProcessingJob | None:
        return await self.session.scalar(
            select(AIProcessingJob)
            .where(
                AIProcessingJob.id == job_id,
                AIProcessingJob.status == AIJobStatus.PROCESSING,
                AIProcessingJob.locked_by == worker_id,
                AIProcessingJob.lock_expires_at.is_not(None),
                AIProcessingJob.lock_expires_at > now,
            )
            .with_for_update()
        )

    @staticmethod
    def _release_lock(job: AIProcessingJob) -> None:
        job.locked_by = None
        job.locked_at = None
        job.lock_expires_at = None
        job.last_heartbeat_at = None

    async def commit(self) -> None:
        await self.session.commit()


def utc_now() -> datetime:
    return datetime.now(UTC)
