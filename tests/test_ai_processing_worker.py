from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models import (
    AIJobStatus,
    AIJobType,
    AIProcessingJob,
    ProcessingPriority,
)
from app.services.ai_processing_worker import (
    AIProcessingWorker,
    HandlerResult,
    PermanentJobError,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Settings:
    ai_worker_id = ""
    ai_worker_concurrency = 1
    ai_queue_poll_interval_seconds = 0.01
    ai_job_lease_seconds = 30
    ai_job_heartbeat_seconds = 10
    ai_job_timeout_seconds = 1
    ai_job_max_attempts = 3
    ai_retry_base_delay_seconds = 2
    ai_retry_max_delay_seconds = 30
    ai_lease_recovery_interval_seconds = 1
    ai_worker_shutdown_timeout_seconds = 1


class QueueState:
    def __init__(self, job):
        self.job = job
        self.claimed = False
        self.completed = None
        self.failed = None
        self.recovered = (0, 0)
        self.capture = None
        self.enqueued = None


class FakeSession:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _model, _entity_id):
        return self.state.capture


class FakeRepository:
    def __init__(self, session):
        self.state = session.state

    async def recover_expired_leases(self, **_fields):
        return self.state.recovered

    async def claim_next(self, **fields):
        if self.state.claimed:
            return None
        self.state.claimed = True
        self.state.job.status = AIJobStatus.PROCESSING
        self.state.job.locked_by = fields["worker_id"]
        self.state.job.attempt_count += 1
        return self.state.job

    async def heartbeat(self, *_args, **_fields):
        return True

    async def complete(self, job_id, **fields):
        self.state.completed = (job_id, fields)
        return True

    async def enqueue(self, **fields):
        self.state.enqueued = fields
        return object(), True

    async def fail(self, job_id, **fields):
        self.state.failed = (job_id, fields)
        return (
            AIJobStatus.RETRYING
            if fields["retryable"]
            else AIJobStatus.FAILED
        )

    async def commit(self):
        return None


class SuccessHandler:
    async def handle(self, _job):
        return {"stage": "CAPTURE_INGESTION"}


class PermanentFailureHandler:
    async def handle(self, _job):
        raise PermanentJobError("invalid evidence manifest")


class ChainingHandler:
    async def handle(self, job):
        return HandlerResult(
            result={"stage": "CAPTURE_INGESTION"},
            next_job_type=AIJobType.PERSON_DETECTION,
            next_payload={"capture_event_id": str(job.capture_event_id)},
        )


class Registry:
    def __init__(self, handler):
        self.handler = handler

    def get(self, _job_type):
        return self.handler


class Dashboard:
    def __init__(self):
        self.messages = []

    async def publish(self, message):
        self.messages.append(message)


def make_job():
    capture_id = uuid4()
    return AIProcessingJob(
        id=uuid4(),
        capture_event_id=capture_id,
        job_type=AIJobType.CAPTURE_INGESTION,
        status=AIJobStatus.QUEUED,
        priority=ProcessingPriority.NORMAL,
        idempotency_key=f"capture-ingestion:{capture_id}",
        attempt_count=0,
        max_attempts=3,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.anyio
async def test_worker_completes_claimed_job_and_publishes_status():
    state = QueueState(make_job())
    dashboard = Dashboard()
    worker = AIProcessingWorker(
        Settings(),
        lambda: FakeSession(state),
        handlers=Registry(SuccessHandler()),
        worker_id="worker-test",
        dashboard_hub=dashboard,
    )

    with patch(
        "app.services.ai_processing_worker.AIJobRepository",
        FakeRepository,
    ):
        processed = await worker.process_one()

    assert processed is True
    assert state.completed[0] == state.job.id
    assert state.completed[1]["worker_id"] == "worker-test"
    assert dashboard.messages[0]["payload"]["status"] == "COMPLETED"


@pytest.mark.anyio
async def test_worker_marks_permanent_failure_without_retry():
    state = QueueState(make_job())
    worker = AIProcessingWorker(
        Settings(),
        lambda: FakeSession(state),
        handlers=Registry(PermanentFailureHandler()),
        worker_id="worker-test",
    )

    with patch(
        "app.services.ai_processing_worker.AIJobRepository",
        FakeRepository,
    ):
        processed = await worker.process_one()

    assert processed is True
    assert state.failed[0] == state.job.id
    assert state.failed[1]["retryable"] is False
    assert state.failed[1]["error_code"] == "PERMANENTJOBERROR"


@pytest.mark.anyio
async def test_worker_enqueues_next_stage_without_finalizing_capture():
    state = QueueState(make_job())
    state.capture = object()
    worker = AIProcessingWorker(
        Settings(),
        lambda: FakeSession(state),
        handlers=Registry(ChainingHandler()),
        worker_id="worker-test",
    )

    with patch(
        "app.services.ai_processing_worker.AIJobRepository",
        FakeRepository,
    ):
        processed = await worker.process_one()

    assert processed is True
    assert state.completed[1]["finalize_capture"] is False
    assert state.enqueued["job_type"] == AIJobType.PERSON_DETECTION
