"""Asynchronous workers consuming durable PostgreSQL AI jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import AIJobType, AIProcessingJob, CaptureEvent, EvidenceAsset
from app.repository import AIJobRepository


class RetryableJobError(RuntimeError):
    """A transient failure that may succeed after backoff."""


class PermanentJobError(RuntimeError):
    """A deterministic failure that must not be retried automatically."""


class AIJobHandler(Protocol):
    async def handle(self, job: AIProcessingJob) -> dict[str, Any] | None: ...


class CaptureIngestionHandler:
    """Validate the capture manifest before later AI stages are scheduled."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def handle(self, job: AIProcessingJob) -> dict[str, Any]:
        async with self._session_factory() as session:
            capture = await session.scalar(
                select(CaptureEvent)
                .where(CaptureEvent.id == job.capture_event_id)
                .options(selectinload(CaptureEvent.evidence_assets))
            )
            if capture is None:
                raise PermanentJobError("Capture event no longer exists")
            assets: list[EvidenceAsset] = [
                asset
                for asset in capture.evidence_assets
                if asset.deleted_at is None
            ]
            if not assets:
                raise PermanentJobError("Capture has no available evidence")
            primary_assets = [asset for asset in assets if asset.is_primary]
            if not primary_assets:
                raise PermanentJobError(
                    "Capture has no primary evidence asset"
                )
            return {
                "stage": "CAPTURE_INGESTION",
                "asset_count": len(assets),
                "asset_types": sorted(
                    {asset.asset_type.value for asset in assets}
                ),
                "unverified_asset_count": sum(
                    asset.checksum_sha256 is None for asset in assets
                ),
                "next_stage": "PERSON_DETECTION",
            }


class AIJobHandlerRegistry:
    def __init__(self, session_factory: Any) -> None:
        self._handlers: dict[AIJobType, AIJobHandler] = {
            AIJobType.CAPTURE_INGESTION: CaptureIngestionHandler(
                session_factory
            )
        }

    def get(self, job_type: AIJobType) -> AIJobHandler:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise PermanentJobError(
                f"No handler registered for job type {job_type.value}"
            )
        return handler


class AIProcessingWorker:
    """Run bounded concurrent handlers with durable leases and heartbeats."""

    def __init__(
        self,
        settings: Any,
        session_factory: Any,
        *,
        handlers: AIJobHandlerRegistry | None = None,
        worker_id: str | None = None,
        dashboard_hub: Any | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._handlers = handlers or AIJobHandlerRegistry(session_factory)
        self._dashboard_hub = dashboard_hub
        self.worker_id = (
            worker_id
            or settings.ai_worker_id.strip()
            or self._default_worker_id()
        )
        self._logger = logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        return bool(self._tasks)

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        await self.recover_expired()
        self._tasks = [
            asyncio.create_task(
                self._run_slot(slot),
                name=f"ai-processing-worker-{slot}",
            )
            for slot in range(self._settings.ai_worker_concurrency)
        ]
        self._logger.info(
            "AI processing worker started worker_id=%s concurrency=%s",
            self.worker_id,
            len(self._tasks),
        )

    async def stop(self) -> None:
        self._stop.set()
        if not self._tasks:
            return
        tasks, self._tasks = self._tasks, []
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._settings.ai_worker_shutdown_timeout_seconds,
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._logger.warning(
                "AI worker shutdown deadline reached; leased jobs will recover"
            )
        self._logger.info("AI processing worker stopped")

    async def recover_expired(self) -> tuple[int, int]:
        async with self._session_factory() as session:
            repository = AIJobRepository(session)
            counts = await repository.recover_expired_leases(
                now=datetime.now(UTC)
            )
            await repository.commit()
        if counts != (0, 0):
            self._logger.warning(
                "Recovered expired AI job leases retrying=%s failed=%s",
                counts[0],
                counts[1],
            )
        return counts

    async def process_one(self) -> bool:
        job = await self._claim()
        if job is None:
            return False
        heartbeat = asyncio.create_task(
            self._heartbeat(job.id),
            name=f"ai-job-heartbeat-{job.id}",
        )
        retryable = True
        try:
            handler = self._handlers.get(job.job_type)
            result = await asyncio.wait_for(
                handler.handle(job),
                timeout=self._settings.ai_job_timeout_seconds,
            )
        except PermanentJobError as error:
            retryable = False
            await self._record_failure(job, error, retryable=False)
        except TimeoutError:
            await self._record_failure(
                job,
                RetryableJobError("AI job execution timed out"),
                retryable=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._record_failure(job, error, retryable=retryable)
        else:
            await self._record_success(job, result)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _run_slot(self, slot: int) -> None:
        last_recovery = 0.0
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            if slot == 0 and (
                loop.time() - last_recovery
                >= self._settings.ai_lease_recovery_interval_seconds
            ):
                try:
                    await self.recover_expired()
                except Exception:
                    self._logger.exception("AI lease recovery failed")
                last_recovery = loop.time()
            try:
                processed = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("AI worker loop failed")
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self._settings.ai_queue_poll_interval_seconds,
                    )
                except TimeoutError:
                    continue

    async def _claim(self) -> AIProcessingJob | None:
        async with self._session_factory() as session:
            repository = AIJobRepository(session)
            job = await repository.claim_next(
                worker_id=self.worker_id,
                now=datetime.now(UTC),
                lease_seconds=self._settings.ai_job_lease_seconds,
            )
            await repository.commit()
            return job

    async def _heartbeat(self, job_id: UUID) -> None:
        while True:
            await asyncio.sleep(self._settings.ai_job_heartbeat_seconds)
            async with self._session_factory() as session:
                repository = AIJobRepository(session)
                renewed = await repository.heartbeat(
                    job_id,
                    worker_id=self.worker_id,
                    now=datetime.now(UTC),
                    lease_seconds=self._settings.ai_job_lease_seconds,
                )
                await repository.commit()
            if not renewed:
                return

    async def _record_success(
        self,
        job: AIProcessingJob,
        result: dict[str, Any] | None,
    ) -> None:
        async with self._session_factory() as session:
            repository = AIJobRepository(session)
            completed = await repository.complete(
                job.id,
                worker_id=self.worker_id,
                result=result,
                now=datetime.now(UTC),
            )
            await repository.commit()
        if not completed:
            self._logger.warning(
                "AI job completion ignored after lease ownership changed job_id=%s",
                job.id,
            )
            return
        await self._publish_status(job, "COMPLETED")

    async def _record_failure(
        self,
        job: AIProcessingJob,
        error: Exception,
        *,
        retryable: bool,
    ) -> None:
        message = str(error).strip() or type(error).__name__
        message = message[:500]
        delay = min(
            self._settings.ai_retry_max_delay_seconds,
            self._settings.ai_retry_base_delay_seconds
            * (2 ** max(0, job.attempt_count - 1)),
        )
        async with self._session_factory() as session:
            repository = AIJobRepository(session)
            status = await repository.fail(
                job.id,
                worker_id=self.worker_id,
                error_code=type(error).__name__.upper(),
                error_message=message,
                retry_delay_seconds=delay,
                retryable=retryable,
                now=datetime.now(UTC),
            )
            await repository.commit()
        self._logger.warning(
            "AI job failed job_id=%s status=%s attempt=%s retryable=%s",
            job.id,
            status.value if status else "LEASE_LOST",
            job.attempt_count,
            retryable,
        )
        if status is not None:
            await self._publish_status(job, status.value)

    async def _publish_status(
        self,
        job: AIProcessingJob,
        status: str,
    ) -> None:
        if self._dashboard_hub is None:
            return
        await self._dashboard_hub.publish(
            {
                "type": "processing_job",
                "payload": {
                    "job_id": str(job.id),
                    "capture_event_id": str(job.capture_event_id),
                    "job_type": job.job_type.value,
                    "status": status,
                },
            }
        )

    @staticmethod
    def _default_worker_id() -> str:
        return f"{socket.gethostname()}:{os.getpid()}"[:160]
