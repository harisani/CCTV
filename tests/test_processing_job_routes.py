from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_ai_job_service, get_database_session
from app.api.routes.processing_jobs import admin_dependency, router
from app.api.security import require_authenticated_user
from app.models import AIJobStatus, AIJobType, ProcessingPriority


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None

    async def commit(self):
        self.commits += 1


class FakeAIJobService:
    def __init__(self):
        now = datetime.now(UTC)
        self.job = SimpleNamespace(
            id=uuid4(),
            capture_event_id=uuid4(),
            job_type=AIJobType.CAPTURE_INGESTION,
            status=AIJobStatus.QUEUED,
            priority=ProcessingPriority.HIGH,
            payload={"capture_event_id": str(uuid4())},
            result=None,
            attempt_count=0,
            max_attempts=5,
            available_at=now,
            locked_at=None,
            lock_expires_at=None,
            started_at=None,
            completed_at=None,
            failed_at=None,
            cancelled_at=None,
            last_error_code=None,
            last_error_message=None,
            created_at=now,
            updated_at=now,
        )

    async def list_jobs(self, **_filters):
        return [self.job], 1

    async def statistics(self):
        return {
            "counts": {"QUEUED": 1},
            "backlog": 1,
            "processing": 0,
            "failed": 0,
            "oldest_available_at": self.job.available_at,
            "oldest_age_seconds": 2.0,
            "average_processing_latency_ms": None,
            "warning_threshold": 100,
            "queue_health": "HEALTHY",
        }

    async def get(self, job_id):
        return self.job if job_id == self.job.id else None

    async def retry(self, job_id):
        if job_id != self.job.id:
            return None
        self.job.status = AIJobStatus.RETRYING
        return self.job

    async def cancel(self, job_id):
        if job_id != self.job.id:
            return None
        self.job.status = AIJobStatus.CANCELLED
        return self.job


def make_client():
    service = FakeAIJobService()
    session = FakeSession()
    user = SimpleNamespace(id=uuid4())

    async def session_override():
        yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_authenticated_user] = lambda: user
    app.dependency_overrides[admin_dependency] = lambda: user
    app.dependency_overrides[get_ai_job_service] = lambda: service
    app.dependency_overrides[get_database_session] = session_override
    return TestClient(app), service, session


def test_job_list_statistics_and_detail_hide_internal_lease_owner():
    client, service, _session = make_client()

    listing = client.get("/api/v1/processing-jobs")
    statistics = client.get("/api/v1/processing-jobs/statistics")
    detail = client.get(f"/api/v1/processing-jobs/{service.job.id}")

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "payload" not in listing.json()["items"][0]
    assert "locked_by" not in listing.json()["items"][0]
    assert statistics.status_code == 200
    assert statistics.json()["queue_health"] == "HEALTHY"
    assert detail.status_code == 200
    assert detail.json()["payload"] is not None
    assert "locked_by" not in detail.json()


def test_job_retry_and_cancel_are_audited():
    client, service, session = make_client()

    service.job.status = AIJobStatus.FAILED
    retry = client.post(
        f"/api/v1/processing-jobs/{service.job.id}/retry"
    )
    cancel = client.post(
        f"/api/v1/processing-jobs/{service.job.id}/cancel"
    )

    assert retry.status_code == 200
    assert cancel.status_code == 200
    assert [item.action for item in session.added] == [
        "AI_PROCESSING_JOB_RETRIED",
        "AI_PROCESSING_JOB_CANCELLED",
    ]
    assert session.commits == 2
