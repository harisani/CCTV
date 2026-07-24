from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import (
    AIJobStatus,
    AIJobType,
    AIProcessingJob,
    CaptureEventStatus,
    ProcessingPriority,
)
from app.repository.ai_job_repository import AIJobRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeSession:
    def __init__(self, scalar_values, capture, *, many_values=None):
        self.scalar_values = list(scalar_values)
        self.capture = capture
        self.many_values = list(many_values or [])
        self.added = []
        self.flushed = 0

    def add(self, value):
        self.added.append(value)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def get(self, _model, identifier):
        if identifier == self.capture.id:
            return self.capture
        return None

    async def scalars(self, _statement):
        return FakeScalarResult(self.many_values)

    async def flush(self):
        self.flushed += 1


def make_job(*, attempt_count=0, max_attempts=3):
    capture_id = uuid4()
    job = AIProcessingJob(
        id=uuid4(),
        capture_event_id=capture_id,
        job_type=AIJobType.CAPTURE_INGESTION,
        status=AIJobStatus.QUEUED,
        priority=ProcessingPriority.HIGH,
        idempotency_key=f"capture-ingestion:{capture_id}",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    capture = SimpleNamespace(
        id=capture_id,
        status=CaptureEventStatus.QUEUED,
        captured_at=datetime.now(UTC),
        processing_started_at=None,
        processed_at=None,
        dashboard_updated_at=None,
        processing_latency_ms=None,
        failed_at=None,
        attempt_count=0,
        retry_count=0,
        failure_reason=None,
        updated_at=datetime.now(UTC),
    )
    return job, capture


@pytest.mark.anyio
async def test_enqueue_is_idempotent_for_existing_key():
    existing, capture = make_job()
    session = FakeSession([existing], capture)
    repository = AIJobRepository(session)

    job, created = await repository.enqueue(
        capture_event=capture,
        job_type=AIJobType.CAPTURE_INGESTION,
        priority=ProcessingPriority.NORMAL,
        idempotency_key=existing.idempotency_key,
        payload={"capture_event_id": str(capture.id)},
        max_attempts=3,
        available_at=datetime.now(UTC),
    )

    assert job is existing
    assert created is False
    assert session.added == []


@pytest.mark.anyio
async def test_claim_sets_lease_and_capture_processing_state():
    job, capture = make_job()
    session = FakeSession([job], capture)
    repository = AIJobRepository(session)
    now = datetime.now(UTC)

    claimed = await repository.claim_next(
        worker_id="worker-a",
        now=now,
        lease_seconds=30,
    )

    assert claimed is job
    assert job.status == AIJobStatus.PROCESSING
    assert job.attempt_count == 1
    assert job.locked_by == "worker-a"
    assert job.lock_expires_at > now
    assert capture.status == CaptureEventStatus.PROCESSING
    assert capture.processing_started_at == now


@pytest.mark.anyio
async def test_completion_requires_lease_owner_and_records_latency():
    job, capture = make_job(attempt_count=1)
    job.status = AIJobStatus.PROCESSING
    job.locked_by = "worker-a"
    job.lock_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    session = FakeSession([job], capture)
    repository = AIJobRepository(session)
    now = datetime.now(UTC)

    completed = await repository.complete(
        job.id,
        worker_id="worker-a",
        result={"stage": "CAPTURE_INGESTION"},
        now=now,
    )

    assert completed is True
    assert job.status == AIJobStatus.COMPLETED
    assert job.locked_by is None
    assert capture.status == CaptureEventStatus.COMPLETED
    assert capture.processed_at == now
    assert capture.processing_latency_ms >= 0
    assert capture.dashboard_updated_at == now


@pytest.mark.anyio
async def test_completion_is_rejected_after_lease_expiry():
    job, capture = make_job(attempt_count=1)
    job.status = AIJobStatus.PROCESSING
    job.locked_by = "worker-a"
    job.lock_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session = FakeSession([None], capture)
    repository = AIJobRepository(session)

    completed = await repository.complete(
        job.id,
        worker_id="worker-a",
        result={"stage": "CAPTURE_INGESTION"},
        now=datetime.now(UTC),
    )

    assert completed is False
    assert job.status == AIJobStatus.PROCESSING
    assert capture.status == CaptureEventStatus.QUEUED


@pytest.mark.anyio
async def test_retry_then_terminal_failure_respects_attempt_limit():
    job, capture = make_job(attempt_count=1, max_attempts=2)
    job.status = AIJobStatus.PROCESSING
    job.locked_by = "worker-a"
    job.lock_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    session = FakeSession([job], capture)
    repository = AIJobRepository(session)
    now = datetime.now(UTC)

    status = await repository.fail(
        job.id,
        worker_id="worker-a",
        error_code="TEMPORARY",
        error_message="temporary failure",
        retry_delay_seconds=5,
        retryable=True,
        now=now,
    )

    assert status == AIJobStatus.RETRYING
    assert job.available_at > now
    assert capture.status == CaptureEventStatus.RETRYING

    job.status = AIJobStatus.PROCESSING
    job.locked_by = "worker-b"
    job.lock_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    job.attempt_count = 2
    session.scalar_values.append(job)
    status = await repository.fail(
        job.id,
        worker_id="worker-b",
        error_code="TEMPORARY",
        error_message="still failing",
        retry_delay_seconds=10,
        retryable=True,
        now=now,
    )

    assert status == AIJobStatus.FAILED
    assert capture.status == CaptureEventStatus.FAILED
    assert capture.failed_at == now


@pytest.mark.anyio
async def test_permanent_failure_never_retries():
    job, capture = make_job(attempt_count=1, max_attempts=5)
    job.status = AIJobStatus.PROCESSING
    job.locked_by = "worker-a"
    job.lock_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    session = FakeSession([job], capture)
    repository = AIJobRepository(session)

    status = await repository.fail(
        job.id,
        worker_id="worker-a",
        error_code="INVALID_CAPTURE",
        error_message="capture manifest is invalid",
        retry_delay_seconds=5,
        retryable=False,
        now=datetime.now(UTC),
    )

    assert status == AIJobStatus.FAILED
    assert job.attempt_count == 1
    assert capture.status == CaptureEventStatus.FAILED


@pytest.mark.anyio
async def test_expired_worker_lease_is_recovered_for_retry():
    job, capture = make_job(attempt_count=1, max_attempts=3)
    job.status = AIJobStatus.PROCESSING
    job.locked_by = "dead-worker"
    job.lock_expires_at = datetime.now(UTC)
    session = FakeSession([], capture, many_values=[job])
    repository = AIJobRepository(session)

    retried, failed = await repository.recover_expired_leases(
        now=datetime.now(UTC)
    )

    assert (retried, failed) == (1, 0)
    assert job.status == AIJobStatus.RETRYING
    assert job.locked_by is None
    assert job.last_error_code == "LEASE_EXPIRED"
    assert capture.status == CaptureEventStatus.RETRYING


@pytest.mark.anyio
async def test_terminal_job_cannot_be_cancelled():
    job, capture = make_job()
    job.status = AIJobStatus.COMPLETED
    session = FakeSession([job], capture)
    repository = AIJobRepository(session)

    with pytest.raises(ValueError, match="cannot be cancelled"):
        await repository.cancel(job.id, now=datetime.now(UTC))

    assert job.status == AIJobStatus.COMPLETED
