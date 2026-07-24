# Phase 1 Application Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen request diagnostics, database failure handling, health checks, login protection, error responses, and Docker runtime safety without breaking the existing CCTV API, dashboard, roles, or realtime pipeline.

**Architecture:** Keep FastAPI as the composition edge and add narrowly scoped request-context, logging, health, and login-limiter components behind dependency-injected interfaces. Preserve existing repositories and business services, make rollback behavior explicit at the async-session boundary, and harden the existing Python 3.12 Docker Compose deployment without adding Redis or another infrastructure service.

**Tech Stack:** Python 3.12, FastAPI, Starlette, Pydantic Settings, SQLAlchemy async, PostgreSQL 16 with pgvector, PyJWT, pytest, Ruff 0.15.22, React 18, Vite 5, Docker, Docker Compose.

## Global Constraints

- Work only on branch `cctv/versi-1`.
- Preserve current roles, permissions, endpoint paths, successful response fields, and WebSocket message shapes.
- Preserve RTSP, YOLO, ByteTrack, ReID, crossing, snapshot, reconciliation, occupancy, and dashboard behavior.
- Do not add Redis, Kubernetes, a telemetry platform, a reverse proxy, or another dependency.
- Do not create a business-schema migration or delete an existing migration, production record, credential, evidence asset, or Docker volume.
- Keep PostgreSQL, API, and dashboard deployable on one Linux server through Docker Compose.
- Production logs must not contain passwords, authorization credentials, RTSP credentials, database credentials, DR passphrases, raw embeddings, or evidence filesystem paths.
- Existing evidence grant/view commits remain explicit and auditable.
- Every production-code change follows red-green-refactor and ends with an independently reviewable commit.
- Use the Docker `test` target for Python 3.12 verification.
- Stop and diagnose if the existing regression suite fails before a task's production change.

---

## File Map

### Request context and configuration

- Create `app/api/request_context.py`: validate, create, bind, retrieve, and reset correlation IDs.
- Create `app/api/middleware.py`: HTTP request context, response header, and access timing.
- Modify `app/config/settings.py`: typed Phase 1 settings.
- Modify `app/app.py`: install request middleware and mark lifecycle readiness.
- Modify `app/api/routes/dashboard_ws.py`: bind a server-side correlation ID without logging the query token.
- Create `tests/test_request_context.py`: context validation, isolation, response header, and WebSocket-safe context tests.

### Structured logging

- Replace `app/utils/logging.py`: environment-aware JSON/text formatting and sensitive-value redaction.
- Create `tests/test_logging.py`: structured fields, context propagation, exception formatting, and redaction tests.

### Database session boundary

- Modify `app/database/session.py`: explicit rollback on request failure.
- Create `tests/test_database_session.py`: rollback, close, and no-implicit-commit tests.

### Health model

- Create `app/services/health_service.py`: bounded PostgreSQL readiness probe.
- Modify `app/services/container.py`: lazily expose the health service.
- Modify `app/api/dependencies.py`: health-service provider.
- Modify `app/api/routes/health.py`: live, ready, and compatible legacy health routes.
- Modify `app/app.py`: lifecycle-ready state.
- Create `tests/test_health_routes.py`: liveness, readiness, dependency failure, timeout, and legacy contract.

### Login limiter

- Create `app/services/login_rate_limiter.py`: bounded single-process attempt limiter.
- Modify `app/services/container.py`: lazily expose the limiter.
- Modify `app/api/dependencies.py`: limiter provider.
- Modify `app/api/routes/auth.py`: enforce limiter without changing the token success contract.
- Create `tests/test_login_rate_limiter.py`: pure service behavior.
- Create `tests/test_auth_rate_limit.py`: route integration and compatibility.

### Safe errors

- Modify `app/api/error_handlers.py`: correlation-aware safe HTTP, validation, database, and unexpected responses.
- Create `tests/test_error_handlers.py`: status mapping, safe content, correlation, and sensitive-input exclusion.

### Docker hardening and documentation

- Modify `Dockerfile`: dedicated non-root production user.
- Modify `docker-compose.yml`: readiness health check and dashboard health check.
- Modify `.env.example`: document the new settings and single-instance limiter limitation.
- Modify `README.md`: Phase 1 operations, storage ownership, health, and logging.
- Create `docs/audits/2026-07-24-phase1-foundation-report.md`: exact implementation and verification evidence.

---

### Task 1: Add Typed Phase 1 Configuration and HTTP Request Context

**Files:**

- Create: `app/api/request_context.py`
- Create: `app/api/middleware.py`
- Modify: `app/config/settings.py`
- Modify: `app/app.py`
- Test: `tests/test_request_context.py`

**Interfaces:**

- Consumes: `Settings.app_env`, FastAPI `Request`, and standard Python
  `contextvars`.
- Produces:
  - `choose_correlation_id(candidate: str | None, max_length: int) -> str`
  - `bind_correlation_id(value: str) -> Token[str | None]`
  - `get_correlation_id() -> str | None`
  - `reset_correlation_id(token: Token[str | None]) -> None`
  - `RequestContextMiddleware(app, max_length: int)`
  - settings fields used by later tasks.

- [ ] **Step 1: Add failing configuration and context tests**

Create `tests/test_request_context.py` with:

```python
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import RequestContextMiddleware
from app.api.request_context import (
    bind_correlation_id,
    choose_correlation_id,
    get_correlation_id,
    reset_correlation_id,
)
from app.config.settings import Settings


def settings_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "postgres_password": "test-postgres-password",
        "jwt_secret": "test-jwt-secret",
        "api_admin_password": "test-admin-password",
    }


def test_phase1_settings_have_safe_bounds() -> None:
    settings = Settings(**settings_values())
    assert settings.log_format == "auto"
    assert settings.correlation_id_max_length == 128
    assert settings.health_database_timeout_seconds == 2.0
    assert settings.login_rate_limit_attempts == 5
    assert settings.login_rate_limit_window_seconds == 60
    assert settings.login_rate_limit_max_entries == 10_000


def test_choose_correlation_id_preserves_only_safe_values() -> None:
    assert choose_correlation_id("client-42:request.7", 128) == "client-42:request.7"
    assert choose_correlation_id("has spaces", 128) != "has spaces"
    assert choose_correlation_id("x" * 129, 128) != "x" * 129


def test_context_binding_is_reset() -> None:
    token = bind_correlation_id("request-one")
    assert get_correlation_id() == "request-one"
    reset_correlation_id(token)
    assert get_correlation_id() is None


def test_context_is_isolated_between_concurrent_tasks() -> None:
    async def worker(value: str) -> str | None:
        token = bind_correlation_id(value)
        try:
            await asyncio.sleep(0)
            return get_correlation_id()
        finally:
            reset_correlation_id(token)

    async def scenario() -> list[str | None]:
        return list(await asyncio.gather(worker("one"), worker("two")))

    assert asyncio.run(scenario()) == ["one", "two"]


def test_middleware_returns_effective_correlation_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, max_length=128)

    @app.get("/probe")
    async def probe() -> dict[str, str | None]:
        return {"correlation_id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/probe", headers={"X-Correlation-ID": "factory-test-1"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "factory-test-1"
    assert response.json() == {"correlation_id": "factory-test-1"}
    assert get_correlation_id() is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_request_context.py -q
```

Expected: test collection fails because `app.api.request_context` and
`app.api.middleware` do not exist and the settings fields are absent.

- [ ] **Step 3: Add the typed settings**

Add these fields to `Settings`:

```python
    log_format: Literal["auto", "text", "json"] = "auto"
    correlation_id_max_length: int = Field(default=128, ge=32, le=256)
    health_database_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    login_rate_limit_attempts: int = Field(default=5, gt=0, le=100)
    login_rate_limit_window_seconds: int = Field(default=60, gt=0, le=3600)
    login_rate_limit_max_entries: int = Field(default=10_000, gt=0, le=1_000_000)
```

Production validation remains unchanged except that invalid typed values must
fail during settings construction.

- [ ] **Step 4: Implement the request-context module**

Create `app/api/request_context.py`:

```python
from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def choose_correlation_id(candidate: str | None, max_length: int) -> str:
    if (
        candidate
        and len(candidate) <= max_length
        and _SAFE_ID.fullmatch(candidate) is not None
    ):
        return candidate
    return str(uuid4())


def bind_correlation_id(value: str) -> Token[str | None]:
    return _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)
```

- [ ] **Step 5: Implement HTTP middleware**

Create `app/api/middleware.py`:

```python
from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.request_context import (
    bind_correlation_id,
    choose_correlation_id,
    reset_correlation_id,
)

logger = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, max_length: int) -> None:
        super().__init__(app)
        self.max_length = max_length

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        correlation_id = choose_correlation_id(
            request.headers.get("X-Correlation-ID"),
            self.max_length,
        )
        token = bind_correlation_id(correlation_id)
        started = monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            logger.info(
                "HTTP request completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000, 3),
                },
            )
            return response
        finally:
            reset_correlation_id(token)
```

- [ ] **Step 6: Register middleware at the application edge**

In `create_app()`, add the middleware before CORS:

```python
    application.add_middleware(
        RequestContextMiddleware,
        max_length=settings.correlation_id_max_length,
    )
```

Import `RequestContextMiddleware` from `app.api.middleware`.

- [ ] **Step 7: Run focused and settings regression tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_request_context.py tests/test_settings_security.py -q
docker run --rm cctv-api-test ruff check \
  app/api/request_context.py app/api/middleware.py app/config/settings.py \
  app/app.py tests/test_request_context.py
```

Expected: all focused tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add app/api/request_context.py app/api/middleware.py app/config/settings.py \
  app/app.py tests/test_request_context.py
git commit -m "feat: add request correlation context"
```

---

### Task 2: Add Environment-Aware Structured Logging and Redaction

**Files:**

- Modify: `app/utils/logging.py`
- Modify: `app/app.py`
- Test: `tests/test_logging.py`

**Interfaces:**

- Consumes: `get_correlation_id()`, `Settings.app_env`,
  `Settings.log_format`, and `Settings.log_level`.
- Produces:
  - `redact_sensitive(value: str) -> str`
  - `JsonFormatter`
  - `CorrelationContextFilter`
  - `configure_logging(level: str, environment: str, format_mode: str) -> None`.

- [ ] **Step 1: Write failing logging tests**

Create `tests/test_logging.py`:

```python
from __future__ import annotations

import json
import logging
from io import StringIO

from app.api.request_context import bind_correlation_id, reset_correlation_id
from app.utils.logging import JsonFormatter, redact_sensitive


def test_redaction_removes_supported_credentials() -> None:
    value = (
        "Authorization: Bearer secret-token "
        "rtsp://camera-user:camera-pass@10.0.0.2/live "
        "password=plain-value"
    )
    redacted = redact_sensitive(value)
    assert "secret-token" not in redacted
    assert "camera-pass" not in redacted
    assert "plain-value" not in redacted
    assert "[REDACTED]" in redacted


def test_json_formatter_adds_context_and_http_fields() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("phase1-json-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    token = bind_correlation_id("request-json-1")
    try:
        logger.info(
            "request complete",
            extra={"http_method": "GET", "http_path": "/health", "http_status": 200},
        )
    finally:
        reset_correlation_id(token)

    payload = json.loads(stream.getvalue())
    assert payload["message"] == "request complete"
    assert payload["correlation_id"] == "request-json-1"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/health"
    assert payload["http_status"] == 200
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_logging.py -q
```

Expected: import fails because `JsonFormatter` and `redact_sensitive` do not
exist.

- [ ] **Step 3: Replace the logging module**

Implement `app/utils/logging.py` with:

```python
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.api.request_context import get_correlation_id

_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_CREDENTIAL_URL = re.compile(
    r"(?i)((?:rtsp|postgresql(?:\+asyncpg)?)://[^:/@\s]+:)[^@\s]+(@)"
)
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|secret|passphrase)=([^&\s,;]+)"
)
_EXTRA_FIELDS = (
    "http_method",
    "http_path",
    "http_status",
    "duration_ms",
    "user_id",
    "exception_type",
)


def redact_sensitive(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _CREDENTIAL_URL.sub(r"\1[REDACTED]\2", value)
    return _ASSIGNMENT.sub(r"\1=[REDACTED]", value)


class CorrelationContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None)
            or get_correlation_id(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact_sensitive(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str, environment: str, format_mode: str) -> None:
    selected = "json" if format_mode == "auto" and environment == "production" else format_mode
    if selected == "auto":
        selected = "text"
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationContextFilter())
    handler.setFormatter(
        JsonFormatter()
        if selected == "json"
        else logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | "
            "%(correlation_id)s | %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

- [ ] **Step 4: Pass environment settings at startup**

Change the lifespan call to:

```python
    configure_logging(
        settings.log_level,
        settings.app_env,
        settings.log_format,
    )
```

- [ ] **Step 5: Run focused tests and scan the logging contract**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_logging.py tests/test_request_context.py -q
docker run --rm cctv-api-test ruff check \
  app/utils/logging.py app/app.py tests/test_logging.py
```

Expected: all focused tests pass, the JSON assertion parses successfully, and
Ruff is clean.

- [ ] **Step 6: Commit**

```bash
git add app/utils/logging.py app/app.py tests/test_logging.py
git commit -m "feat: add structured application logging"
```

---

### Task 3: Make Request-Session Rollback Explicit

**Files:**

- Modify: `app/database/session.py`
- Test: `tests/test_database_session.py`

**Interfaces:**

- Consumes: module-level `SessionLocal`.
- Produces: `get_session()` yielding one `AsyncSession`, rolling back on an
  escaping exception, never committing implicitly, and closing through the
  async context manager.

- [ ] **Step 1: Write failing session-boundary tests**

Create `tests/test_database_session.py`:

```python
from __future__ import annotations

import asyncio

import pytest

import app.database.session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1


def test_session_rolls_back_and_closes_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = FakeSession()
        monkeypatch.setattr(session_module, "SessionLocal", lambda: session)
        dependency = session_module.get_session()

        assert await anext(dependency) is session
        with pytest.raises(RuntimeError, match="boom"):
            await dependency.athrow(RuntimeError("boom"))

        assert session.rollbacks == 1
        assert session.commits == 0
        assert session.closed is True

    asyncio.run(scenario())


def test_session_success_does_not_commit_implicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = FakeSession()
        monkeypatch.setattr(session_module, "SessionLocal", lambda: session)
        dependency = session_module.get_session()

        assert await anext(dependency) is session
        await dependency.aclose()

        assert session.rollbacks == 0
        assert session.commits == 0
        assert session.closed is True

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_database_session.py -q
```

Expected: the failure-path assertion reports zero rollbacks.

- [ ] **Step 3: Implement the minimal rollback boundary**

Change `get_session()` to:

```python
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one request session and roll back any escaping failure."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

Do not add an automatic commit.

- [ ] **Step 4: Run focused and repository regression tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_database_session.py tests/test_evidence_routes.py \
  tests/test_pipeline_repository_presence.py -q
docker run --rm cctv-api-test ruff check \
  app/database/session.py tests/test_database_session.py
```

Expected: all selected tests pass and Ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add app/database/session.py tests/test_database_session.py
git commit -m "fix: roll back failed request sessions"
```

---

### Task 4: Split Liveness, Readiness, and Legacy Health

**Files:**

- Create: `app/services/health_service.py`
- Modify: `app/services/container.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/api/routes/health.py`
- Modify: `app/app.py`
- Test: `tests/test_health_routes.py`

**Interfaces:**

- Consumes: `AsyncSession`, `Settings.health_database_timeout_seconds`, and
  `request.app.state.ready`.
- Produces:
  - `HealthService.database_ready(session, timeout_seconds) -> bool`
  - `GET /health/live`
  - `GET /health/ready`
  - unchanged successful `GET /health` response contract.

- [ ] **Step 1: Write failing health-route tests**

Create `tests/test_health_routes.py` using a small FastAPI app with dependency
overrides. Define a fake session whose async `execute()` increments
`execute_calls` and raises its configured `SQLAlchemyError`. Include these
route assertions:

```python
def test_liveness_does_not_touch_database() -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert session.execute_calls == 0


def test_readiness_returns_503_before_startup_is_ready() -> None:
    app.state.ready = False
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Application is not ready"


def test_readiness_returns_503_without_exposing_database_error() -> None:
    app.state.ready = True
    session.error = SQLAlchemyError("postgresql://user:secret@db/private")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "secret" not in response.text


def test_legacy_health_success_contract_is_unchanged() -> None:
    app.state.ready = True
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "test",
        "database": "connected",
    }
```

Use a fake session with `execute_calls`, an async `execute()`, and a configurable
exception. Override `get_database_session`, `get_app_settings`, and
`get_health_service`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_health_routes.py -q
```

Expected: `/health/live` and `/health/ready` return `404`, and the health-service
dependency is absent.

- [ ] **Step 3: Implement the health service**

Create `app/services/health_service.py`:

```python
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class HealthService:
    async def database_ready(
        self,
        session: AsyncSession,
        timeout_seconds: float,
    ) -> bool:
        try:
            async with asyncio.timeout(timeout_seconds):
                await session.execute(text("SELECT 1"))
        except (SQLAlchemyError, TimeoutError):
            return False
        return True
```

Do not catch `asyncio.CancelledError`.

- [ ] **Step 4: Expose the service through dependency injection**

Add to `ServiceContainer`:

```python
    @cached_property
    def health(self) -> HealthService:
        return HealthService()
```

Import `HealthService`. Add to `app/api/dependencies.py`:

```python
def get_health_service() -> Generator[HealthService, None, None]:
    yield get_service_container().health
```

- [ ] **Step 5: Implement the three health routes**

Keep `HealthResponse` for the legacy endpoint and add:

```python
class LiveResponse(BaseModel):
    status: str


@router.get("/health/live", response_model=LiveResponse)
async def health_live() -> LiveResponse:
    return LiveResponse(status="ok")
```

Both `/health/ready` and `/health` call the injected health service. Readiness
first checks `request.app.state.ready`. A failed probe raises:

```python
raise HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Database unavailable",
)
```

The legacy success response remains exactly:

```python
HealthResponse(
    status="ok",
    environment=settings.app_env,
    database="connected",
)
```

- [ ] **Step 6: Mark lifecycle readiness**

In `create_app()` initialize:

```python
    application.state.ready = False
```

Rename the lifespan parameter to `application`. Set
`application.state.ready = True` immediately before `yield`, and set it to
`False` at the start of the `finally` block.

- [ ] **Step 7: Run focused and application regression tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_health_routes.py tests/test_request_context.py \
  tests/test_service_container.py -q
docker run --rm cctv-api-test ruff check \
  app/services/health_service.py app/services/container.py \
  app/api/dependencies.py app/api/routes/health.py app/app.py \
  tests/test_health_routes.py
```

Expected: all selected tests pass and Ruff is clean.

- [ ] **Step 8: Commit**

```bash
git add app/services/health_service.py app/services/container.py \
  app/api/dependencies.py app/api/routes/health.py app/app.py \
  tests/test_health_routes.py
git commit -m "feat: add application readiness checks"
```

---

### Task 5: Add a Bounded Single-Instance Login Limiter

**Files:**

- Create: `app/services/login_rate_limiter.py`
- Modify: `app/services/container.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/api/routes/auth.py`
- Test: `tests/test_login_rate_limiter.py`
- Test: `tests/test_auth_rate_limit.py`

**Interfaces:**

- Consumes: Phase 1 limiter settings, normalized username, and
  `request.client.host`.
- Produces:
  - `LoginRateLimiter.build_key(username: str, client_host: str) -> str`
  - `LoginRateLimiter.retry_after(key: str) -> int | None`
  - `LoginRateLimiter.record_failure(key: str) -> int | None`
  - `LoginRateLimiter.reset(key: str) -> None`
  - dependency `get_login_rate_limiter()`.

- [ ] **Step 1: Write failing pure-service tests**

Create `tests/test_login_rate_limiter.py` with a controllable monotonic clock:

```python
from app.services.login_rate_limiter import LoginRateLimiter


def test_limiter_blocks_at_boundary_then_expires() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(
        max_attempts=2,
        window_seconds=30,
        max_entries=10,
        clock=lambda: now[0],
    )
    key = limiter.build_key(" Admin ", "10.0.0.1")

    assert limiter.retry_after(key) is None
    assert limiter.record_failure(key) is None
    assert limiter.record_failure(key) == 30
    assert limiter.retry_after(key) == 30

    now[0] = 131.0
    assert limiter.retry_after(key) is None


def test_success_reset_and_key_isolation() -> None:
    limiter = LoginRateLimiter(2, 30, 10)
    first = limiter.build_key("admin", "10.0.0.1")
    second = limiter.build_key("admin", "10.0.0.2")
    limiter.record_failure(first)
    limiter.reset(first)
    assert limiter.retry_after(first) is None
    assert first != second
```

- [ ] **Step 2: Run pure tests and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_login_rate_limiter.py -q
```

Expected: import fails because `app.services.login_rate_limiter` does not exist.

- [ ] **Step 3: Implement the limiter**

Create `app/services/login_rate_limiter.py` with a locked, bounded mapping:

```python
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable


@dataclass(slots=True)
class _Attempt:
    failures: int
    first_failure_at: float
    blocked_until: float | None = None


class LoginRateLimiter:
    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._attempts: dict[str, _Attempt] = {}
        self._lock = Lock()

    @staticmethod
    def build_key(username: str, client_host: str) -> str:
        normalized = f"{username.strip().lower()}|{client_host.strip()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def retry_after(self, key: str) -> int | None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is None or attempt.blocked_until is None:
                return None
            return max(1, math.ceil(attempt.blocked_until - now))

    def record_failure(self, key: str) -> int | None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is None:
                self._make_room()
                attempt = _Attempt(failures=0, first_failure_at=now)
                self._attempts[key] = attempt
            attempt.failures += 1
            if attempt.failures >= self.max_attempts:
                attempt.blocked_until = now + self.window_seconds
                return self.window_seconds
            return None

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, attempt in self._attempts.items()
            if (
                attempt.blocked_until is not None
                and attempt.blocked_until <= now
            )
            or (
                attempt.blocked_until is None
                and now - attempt.first_failure_at >= self.window_seconds
            )
        ]
        for key in expired:
            self._attempts.pop(key, None)

    def _make_room(self) -> None:
        if len(self._attempts) < self.max_entries:
            return
        oldest = min(
            self._attempts,
            key=lambda key: self._attempts[key].first_failure_at,
        )
        self._attempts.pop(oldest, None)
```

- [ ] **Step 4: Wire the singleton service through the container**

Add to `ServiceContainer`:

```python
    @cached_property
    def login_limiter(self) -> LoginRateLimiter:
        return LoginRateLimiter(
            self.settings.login_rate_limit_attempts,
            self.settings.login_rate_limit_window_seconds,
            self.settings.login_rate_limit_max_entries,
        )
```

Add to `app/api/dependencies.py`:

```python
def get_login_rate_limiter() -> Generator[LoginRateLimiter, None, None]:
    yield get_service_container().login_limiter
```

- [ ] **Step 5: Write failing route-integration tests**

Create `tests/test_auth_rate_limit.py`. Build a small FastAPI app with the auth
router and override settings, repository, and limiter dependencies. Prove:

```python
def test_failed_login_is_limited_at_configured_boundary() -> None:
    first = client.post("/api/v1/auth/token", data=invalid_credentials)
    second = client.post("/api/v1/auth/token", data=invalid_credentials)
    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json()["detail"] == "Too many login attempts"


def test_successful_login_resets_limiter_and_keeps_token_contract() -> None:
    response = client.post("/api/v1/auth/token", data=valid_credentials)
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type"}
    assert limiter.retry_after(expected_key) is None
```

The fake `UserService.authenticate` path may be achieved by a minimal fake
repository and a pre-hashed test user; do not weaken production password
verification.

- [ ] **Step 6: Apply the limiter in the login route**

Add `Request` and the limiter dependency. Use only `request.client.host` and
fall back to `"unknown"` when `request.client` is absent. Do not trust
`X-Forwarded-For` in this single-server phase.

The route flow is:

```python
    client_host = request.client.host if request.client else "unknown"
    key = limiter.build_key(form.username, client_host)
    retry_after = limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        user = await UserService(repository).authenticate(
            form.username,
            form.password,
            settings,
        )
    except HTTPException as error:
        if error.status_code == status.HTTP_401_UNAUTHORIZED:
            retry_after = limiter.record_failure(key)
            if retry_after is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many login attempts",
                    headers={"Retry-After": str(retry_after)},
                ) from error
        raise
    limiter.reset(key)
    return TokenResponse(access_token=create_access_token(settings, user))
```

- [ ] **Step 7: Run focused and authentication regression tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_login_rate_limiter.py tests/test_auth_rate_limit.py \
  tests/test_password_service.py tests/test_evidence_routes.py -q
docker run --rm cctv-api-test ruff check \
  app/services/login_rate_limiter.py app/services/container.py \
  app/api/dependencies.py app/api/routes/auth.py \
  tests/test_login_rate_limiter.py tests/test_auth_rate_limit.py
```

Expected: all selected tests pass, the token success shape is unchanged, and
Ruff is clean.

- [ ] **Step 8: Commit**

```bash
git add app/services/login_rate_limiter.py app/services/container.py \
  app/api/dependencies.py app/api/routes/auth.py \
  tests/test_login_rate_limiter.py tests/test_auth_rate_limit.py
git commit -m "security: rate limit failed logins"
```

---

### Task 6: Make HTTP Errors Correlation-Aware and Safe

**Files:**

- Modify: `app/api/error_handlers.py`
- Modify: `app/api/routes/dashboard_ws.py`
- Test: `tests/test_error_handlers.py`
- Test: `tests/test_dashboard_hub.py`

**Interfaces:**

- Consumes: `get_correlation_id()` and the Task 1 context-binding functions.
- Produces:
  - additive `correlation_id` field on error responses;
  - sanitized validation details without submitted input values;
  - server-side WebSocket connection correlation context.

- [ ] **Step 1: Write failing error-contract tests**

Create `tests/test_error_handlers.py` with a FastAPI test app, Task 1 middleware,
and registered exception handlers. Cover:

```python
def test_http_error_preserves_status_headers_and_adds_correlation() -> None:
    response = client.get(
        "/limited",
        headers={"X-Correlation-ID": "error-test-1"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json() == {
        "detail": "Too many requests",
        "correlation_id": "error-test-1",
    }


def test_validation_error_does_not_echo_sensitive_input() -> None:
    response = client.post(
        "/validate",
        headers={"X-Correlation-ID": "validation-test-1"},
        json={"password": ["sensitive-submitted-value"]},
    )
    assert response.status_code == 422
    assert response.json()["correlation_id"] == "validation-test-1"
    assert "sensitive-submitted-value" not in response.text


def test_unexpected_error_hides_internal_detail() -> None:
    response = client.get("/explode")
    assert response.status_code == 500
    assert "postgresql://" not in response.text
    assert response.json()["detail"] == "An unexpected server error occurred."
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest tests/test_error_handlers.py -q
```

Expected: HTTP and validation errors omit `correlation_id`, and validation
details include submitted input.

- [ ] **Step 3: Implement safe handlers**

Add handlers for Starlette `HTTPException` and FastAPI
`RequestValidationError`. Preserve HTTP exception headers. Build all response
content through:

```python
def error_content(detail: object) -> dict[str, object]:
    return {
        "detail": detail,
        "correlation_id": get_correlation_id(),
    }


def safe_validation_errors(error: RequestValidationError) -> list[dict[str, object]]:
    return [
        {
            "type": item["type"],
            "loc": list(item["loc"]),
            "msg": item["msg"],
        }
        for item in error.errors()
    ]
```

Database handlers must log an exception type and correlation context without
formatting `error.orig`, SQL, a connection URL, or request data into the
message. Unexpected exceptions retain `logger.exception(...)`.

- [ ] **Step 4: Bind WebSocket context without logging credentials**

At the beginning of `dashboard_websocket`, create a UUID correlation ID and
bind it. Reset it in an outer `finally` block. Add connection/disconnection
logs that include `user_id` after authentication but never interpolate
`websocket.url`, query parameters, or `token`.

The existing query-token authentication and message shapes remain unchanged in
this phase.

- [ ] **Step 5: Add a WebSocket context regression**

Extend `tests/test_dashboard_hub.py` with a fake WebSocket whose
`query_params` contains an invalid token. Monkeypatch
`app.api.routes.dashboard_ws.bind_correlation_id` and
`reset_correlation_id`, then assert:

```python
def test_dashboard_websocket_binds_context_without_logging_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bound: list[str] = []
    reset: list[object] = []
    marker = object()

    monkeypatch.setattr(
        dashboard_ws_module,
        "bind_correlation_id",
        lambda value: bound.append(value) or marker,
    )
    monkeypatch.setattr(
        dashboard_ws_module,
        "reset_correlation_id",
        lambda token: reset.append(token),
    )
    websocket = FakeWebSocket(query_params={"token": "secret-websocket-token"})

    asyncio.run(dashboard_ws_module.dashboard_websocket(websocket))

    UUID(bound[0])
    assert reset == [marker]
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION
    assert "secret-websocket-token" not in caplog.text
```

Define `FakeWebSocket.close()` as an async method that records `close_code`.
Use the module import
`import app.api.routes.dashboard_ws as dashboard_ws_module`.

- [ ] **Step 6: Run focused and API regression tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest \
  tests/test_error_handlers.py tests/test_dashboard_hub.py \
  tests/test_evidence_routes.py tests/test_snapshot_routes.py -q
docker run --rm cctv-api-test ruff check \
  app/api/error_handlers.py app/api/routes/dashboard_ws.py \
  tests/test_error_handlers.py tests/test_dashboard_hub.py
```

Expected: all selected tests pass, errors retain the existing status semantics,
and Ruff is clean.

- [ ] **Step 7: Commit**

```bash
git add app/api/error_handlers.py app/api/routes/dashboard_ws.py \
  tests/test_error_handlers.py tests/test_dashboard_hub.py
git commit -m "security: harden correlated error responses"
```

---

### Task 7: Run the API as Non-root and Use Readiness in Compose

**Files:**

- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Test: Docker runtime commands in this task.

**Interfaces:**

- Consumes: `GET /api/v1/health/ready`, UID/GID `10001`, and the existing
  `/service/storage` bind mount.
- Produces: a non-root production API image, readiness-based health check,
  dashboard health check, and documented Linux storage ownership.

- [ ] **Step 1: Record the failing non-root runtime check**

Run before changing the Dockerfile:

```bash
docker compose build api
docker compose run --rm --no-deps --entrypoint id api -u
```

Expected: output is `0`, proving the production image currently runs as root.

- [ ] **Step 2: Add a dedicated production user**

In the base stage, after package installation, create the account:

```dockerfile
RUN groupadd --system --gid 10001 cctv \
    && useradd --system --uid 10001 --gid cctv \
        --home-dir /service --shell /usr/sbin/nologin cctv
```

After creating storage, grant only required ownership:

```dockerfile
RUN mkdir -p /service/storage \
    && chown -R cctv:cctv /service/storage \
    && chmod +x /entrypoint.sh
```

Keep the test stage able to run its existing commands. Add only to the
production stage:

```dockerfile
USER 10001:10001
```

- [ ] **Step 3: Switch Compose health checks**

Change the API health URL to:

```yaml
http://localhost:8000/api/v1/health/ready
```

Add a dashboard health check:

```yaml
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:5173"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 20s
```

Retain `restart: unless-stopped` for API, dashboard, and PostgreSQL.

- [ ] **Step 4: Document environment and host preparation**

Add to `.env.example`:

```dotenv
LOG_FORMAT=auto
CORRELATION_ID_MAX_LENGTH=128
HEALTH_DATABASE_TIMEOUT_SECONDS=2
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
LOGIN_RATE_LIMIT_MAX_ENTRIES=10000
```

Document in `README.md`:

```bash
sudo install -d -o 10001 -g 10001 storage
```

Explain that this command prepares the Linux bind-mounted evidence directory;
it is not required for Docker Desktop on macOS when file sharing already grants
write access. Document `/health/live`, `/health/ready`, structured production
logs, and the single-instance limitation of the in-memory login limiter.

- [ ] **Step 5: Build and verify non-root runtime**

Run:

```bash
docker compose build api dashboard
docker compose run --rm --no-deps --entrypoint id api -u
docker compose config --quiet
```

Expected:

- both images build;
- the API UID output is `10001`;
- Compose configuration exits zero.

- [ ] **Step 6: Verify writable storage without changing repository evidence**

Run:

```bash
docker compose run --rm --no-deps --entrypoint python api -c \
  "from pathlib import Path; p=Path('/service/storage/.phase1-write-test'); p.write_text('ok'); p.unlink()"
```

Expected: command exits zero and the temporary probe file is removed.

- [ ] **Step 7: Run regression tests after container changes**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
docker compose run --rm --no-deps dashboard npm test
docker compose run --rm --no-deps dashboard npm run build
```

Expected: all backend and dashboard tests pass, Ruff is clean, and the
dashboard production build succeeds.

- [ ] **Step 8: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example README.md
git commit -m "build: harden Phase 1 containers"
```

---

### Task 8: Verify Migration, Runtime Compatibility, and Publish the Phase 1 Report

**Files:**

- Create: `docs/audits/2026-07-24-phase1-foundation-report.md`
- Modify only if evidence requires correction: `README.md`

**Interfaces:**

- Consumes: all Phase 1 commits and the approved design.
- Produces: complete reproducible evidence, rollback notes, and a final review
  package.

- [ ] **Step 1: Run the complete Python 3.12 gate**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test python --version
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
```

Expected:

- Python reports a `3.12.x` version;
- pytest reports zero failures;
- Ruff reports `All checks passed!`.

- [ ] **Step 2: Prove Alembic upgrade on a disposable database**

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Create the disposable database:

```bash
docker compose exec -T postgres sh -c \
  'dropdb --if-exists -U "$POSTGRES_USER" cctv_phase1_verify && createdb -U "$POSTGRES_USER" cctv_phase1_verify'
```

Upgrade it:

```bash
docker compose run --rm --no-deps \
  -e POSTGRES_DB=cctv_phase1_verify api alembic upgrade head
```

Inspect the head:

```bash
docker compose run --rm --no-deps \
  -e POSTGRES_DB=cctv_phase1_verify api alembic current
```

Expected: Alembic reports the existing current head; Phase 1 adds no migration.

Remove only the explicitly named disposable database:

```bash
docker compose exec -T postgres sh -c \
  'dropdb --if-exists -U "$POSTGRES_USER" cctv_phase1_verify'
```

- [ ] **Step 3: Verify the Compose runtime**

Run:

```bash
docker compose up -d
docker compose ps
curl --fail --silent http://localhost:8000/api/v1/health/live
curl --fail --silent http://localhost:8000/api/v1/health/ready
```

Expected:

- PostgreSQL, API, and dashboard become healthy;
- liveness returns `{"status":"ok"}`;
- readiness returns HTTP 200 with connected database status.

Stop the application without deleting data or volumes:

```bash
docker compose stop
```

- [ ] **Step 4: Verify compatibility and security contracts**

Run:

```bash
git diff --check
docker compose config --quiet
```

Run source scans:

```bash
! rg -n 'access_token=.*\?|\?access_token|snapshot_url|/storage/' \
  dashboard/src app/api app/services app/repository \
  -g '*.js' -g '*.jsx' -g '*.py'
! rg -n 'image_path|metadata_path' \
  app/api/routes/snapshots.py app/api/schemas.py
```

Run a log fixture containing a bearer token, RTSP credential, password
assignment, and database URL through `redact_sensitive`; assert none of the
secret values appears in output.

Expected: all commands exit zero and both prohibited source scans are empty.

- [ ] **Step 5: Write the Phase 1 report**

Create `docs/audits/2026-07-24-phase1-foundation-report.md` with these concrete
sections:

```markdown
# Phase 1 Application Foundation Report

## Scope
## Approved Compatibility Boundaries
## Commits
## Changed Files and Responsibilities
## RED/GREEN Evidence by Task
## Full Test and Ruff Results
## Alembic Disposable-Database Result
## Docker Build and Runtime Result
## Correlation and Logging Security Result
## Health and Login-Limiter Result
## Non-root and Storage-Write Result
## Rollback Procedure
## Deferred Work
## Known Non-blocking Concerns
```

Populate every section with exact commands, exit status, counts, commit IDs,
and observed output. Do not include environment-file content, credentials,
tokens, RTSP URLs, database URLs, or evidence paths.

- [ ] **Step 6: Self-review the complete Phase 1 diff**

Check:

```bash
git status --short
git diff --check
git diff --stat 80cc2f9..HEAD
```

Confirm:

- no current role enum or permission behavior changed;
- no endpoint or successful dashboard response lost a field;
- no migration was added or removed;
- no dependency was added;
- no pipeline, occupancy, reconciliation, or camera behavior changed;
- no raw credential or evidence path appears in public/logging code;
- every new setting is documented;
- every new public behavior has a regression test.

- [ ] **Step 7: Commit the report**

```bash
git add docs/audits/2026-07-24-phase1-foundation-report.md README.md
git commit -m "docs: record Phase 1 foundation evidence"
```

- [ ] **Step 8: Request independent review**

Build a review package from the Phase 1 design commit to the report commit.
Require the reviewer to categorize Critical, Important, and Minor findings and
explicitly verify:

- backward compatibility;
- correlation-context isolation;
- sensitive-log redaction;
- transaction rollback;
- readiness semantics;
- limiter bounds and single-instance documentation;
- non-root runtime and writable storage;
- absence of unrelated scope changes.

Do not declare Phase 1 complete while a Critical or Important finding remains.

---

## Final Acceptance Gate

Before declaring Phase 1 complete, rerun:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test python --version
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
docker compose build api dashboard
docker compose run --rm --no-deps dashboard npm test
docker compose run --rm --no-deps dashboard npm run build
docker compose config --quiet
git diff --check
```

Expected: Python 3.12, zero backend and dashboard test failures, clean Ruff,
successful images and frontend production build, valid Compose configuration,
and clean whitespace.

The completion report must state the actual measured test counts and timings;
it must not copy expected values from this plan.
