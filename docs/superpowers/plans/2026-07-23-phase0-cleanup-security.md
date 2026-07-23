# Phase 0 Cleanup and Security Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current CCTV project reproducible from a clean checkout, establish a Python 3.12 verification baseline, protect snapshot evidence from unauthenticated access, validate production secrets, and remove only dead code proven to have no active references.

**Architecture:** Preserve the current runtime pipeline during Phase 0 while repairing its source-control and security boundaries. Evidence access moves behind a focused service and short-lived signed URL flow; production configuration fails closed; a Docker test target provides repeatable verification without installing development tools in the production image.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy async, PostgreSQL, PyJWT, pytest, ruff, React 18, Vite 5, Docker, Docker Compose.

## Global Constraints

- Do not delete production data, evidence, credentials, or historical migrations.
- Do not alter the realtime pipeline, midnight reconciliation, occupancy semantics, or camera topology in this plan.
- Do not expose raw embeddings or filesystem paths to the frontend.
- Treat snapshots, face/periocular crops, body images, and video as sensitive evidence.
- Every evidence grant and content retrieval must be auditable.
- Keep the existing dependency set unless a task explicitly uses a dependency already declared by the project.
- Every code change follows red-green-refactor and ends with an independently reviewable commit.
- Stop execution if the Docker daemon is unavailable or the existing test baseline fails after source reproducibility is repaired.
- Work only on branch `cctv/versi-1`.
- Preserve the approved architecture document at `docs/superpowers/specs/2026-07-23-cctv-factory-security-design.md`.

---

## File Map

### Source reproducibility and verification

- Modify `.gitignore`: ignore only root runtime storage.
- Modify `.dockerignore`: ignore only root runtime storage.
- Modify `Dockerfile`: add isolated `test` and `production` stages.
- Modify `docker-compose.yml`: build the `production` target.
- Track `app/storage/__init__.py`: public storage service exports.
- Track `app/storage/snapshot_service.py`: active snapshot implementation.

### Production configuration

- Modify `app/config/settings.py`: fail-closed production validation and evidence signing settings.
- Modify `.env.example`: document evidence signing configuration and production-safe requirements.
- Create `tests/test_settings_security.py`: production validation tests.

### Evidence authorization

- Create `app/services/evidence_access_service.py`: sign, validate, and resolve snapshot evidence.
- Create `app/api/routes/evidence.py`: grant and retrieve evidence.
- Modify `app/api/router.py`: register evidence routes.
- Modify `app/api/schemas.py`: expose snapshot IDs and access-grant response.
- Modify `app/repository/event_repository.py`: return snapshot IDs rather than filesystem paths.
- Modify `app/api/routes/events.py`: remove public storage URL generation.
- Modify `app/repository/pipeline_repository.py`: publish snapshot IDs.
- Modify `app/services/realtime_pipeline.py`: stop publishing `/storage` URLs.
- Modify `app/app.py`: remove the public static storage mount.
- Create `tests/test_evidence_access_service.py`: token and path-boundary unit tests.
- Create `tests/test_evidence_routes.py`: grant, signed retrieval, audit, and public-mount tests.

### Dashboard compatibility

- Modify `dashboard/src/api.js`: request a short-lived snapshot access URL.
- Modify `dashboard/src/App.jsx`: open snapshots using snapshot IDs.

### Proven cleanup and documentation

- Delete `app/ai/__init__.py`: empty package with no active import.
- Delete `app/repository/tracking_repository.py`: unused repository.
- Modify `app/repository/__init__.py`: remove the dead export.
- Create `docs/audits/2026-07-23-phase0-cleanup-report.md`: deletion and verification record.

---

### Task 1: Restore Reproducible Source and Add a Python 3.12 Test Image

**Files:**

- Modify: `.gitignore`
- Modify: `.dockerignore`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Track: `app/storage/__init__.py`
- Track: `app/storage/snapshot_service.py`
- Test: `tests/test_snapshot_service.py`

**Interfaces:**

- Consumes: existing `SnapshotService`, project requirements, and Docker Compose API build.
- Produces: tracked snapshot source, Docker target `test`, Docker target `production`, and a repeatable Python 3.12 test command.

- [ ] **Step 1: Verify the known source-control failure**

Run:

```bash
git check-ignore -v app/storage/snapshot_service.py
git ls-files --error-unmatch app/storage/snapshot_service.py
```

Expected:

- the first command reports `.gitignore:7:storage/`;
- the second command fails because the active source is not tracked.

- [ ] **Step 2: Scope root runtime ignores**

Replace `.gitignore` with:

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
/storage/
dashboard/node_modules/
dashboard/dist/
.DS_Store
```

Replace `.dockerignore` with:

```dockerignore
.git
.env
.venv
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
/storage/
dashboard/node_modules/
dashboard/dist/
.DS_Store
```

- [ ] **Step 3: Create production and test Docker stages**

Replace `Dockerfile` with:

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp

WORKDIR /service

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir \
        torch==2.5.1 torchvision==0.20.1 --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import torchreid; torchreid.models.build_model(name='osnet_x1_0', num_classes=1000, loss='softmax', pretrained=True)"

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN mkdir -p /service/storage \
    && chmod +x /entrypoint.sh

FROM base AS test

RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
COPY examples ./examples
ENTRYPOINT []
CMD ["pytest", "-q"]

FROM base AS production

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Add `target: production` to the API build in `docker-compose.yml`:

```yaml
  api:
    build:
      context: .
      target: production
      args:
        TORCH_INDEX_URL: ${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}
```

- [ ] **Step 4: Verify source visibility before staging**

Run:

```bash
test -f app/storage/__init__.py
test -f app/storage/snapshot_service.py
test -z "$(git check-ignore app/storage/snapshot_service.py)"
git status --short app/storage .gitignore .dockerignore Dockerfile docker-compose.yml
```

Expected:

- both source files exist;
- `git check-ignore` prints nothing;
- `app/storage` appears as untracked source ready to stage.

- [ ] **Step 5: Build and run the test image**

Precondition: Docker Desktop is running. If Docker cannot connect to its daemon,
stop this plan and report the blocker.

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
docker compose build api dashboard
```

Expected:

- pytest completes with zero failures;
- ruff completes with zero violations;
- API and dashboard images build successfully.

If an existing test fails after `app/storage` is available in the image, stop
and diagnose the baseline before continuing.

- [ ] **Step 6: Commit the reproducibility repair**

```bash
git add .gitignore .dockerignore Dockerfile docker-compose.yml \
  app/storage/__init__.py app/storage/snapshot_service.py
git commit -m "build: make CCTV source reproducible"
```

---

### Task 2: Fail Closed on Unsafe Production Configuration

**Files:**

- Create: `tests/test_settings_security.py`
- Modify: `app/config/settings.py`
- Modify: `.env.example`

**Interfaces:**

- Consumes: Pydantic `Settings` and environment variables.
- Produces: `Settings.evidence_signing_secret`,
  `Settings.evidence_access_token_expire_seconds`, and production validation.

- [ ] **Step 1: Write failing production-security tests**

Create `tests/test_settings_security.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def secure_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "cors_allowed_origins": "https://security.example.test",
        "postgres_password": "postgres-production-password-2026",
        "jwt_secret": "jwt-signing-secret-with-at-least-32-characters",
        "api_admin_password": "admin-production-password-2026",
        "evidence_signing_secret": "evidence-signing-secret-with-at-least-32-characters",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("debug", True),
        ("jwt_secret", "replace_with_a_long_random_secret"),
        ("evidence_signing_secret", "short"),
        ("postgres_password", "cctv_user"),
        ("api_admin_password", "change-this-admin-password"),
        ("cors_allowed_origins", "*"),
        ("jwt_algorithm", "none"),
    ],
)
def test_production_rejects_unsafe_configuration(field: str, value: object) -> None:
    values = secure_values()
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)


def test_production_accepts_explicit_secure_configuration() -> None:
    settings = Settings(**secure_values())

    assert settings.app_env == "production"
    assert settings.jwt_algorithm == "HS256"
    assert settings.evidence_access_token_expire_seconds == 60


@pytest.mark.parametrize("seconds", [9, 301])
def test_evidence_access_expiry_is_bounded(seconds: int) -> None:
    values = secure_values()
    values["evidence_access_token_expire_seconds"] = seconds
    with pytest.raises(ValidationError):
        Settings(**values)
```

- [ ] **Step 2: Run the tests and observe failure**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_settings_security.py -q
```

Expected: collection or assertions fail because evidence settings and the
production validator do not exist.

- [ ] **Step 3: Implement production validation**

Change the imports at the top of `app/config/settings.py` to:

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Add these fields immediately after the JWT settings:

```python
    evidence_signing_secret: str = Field(
        default="development-only-evidence-key-change-this-before-production",
        repr=False,
    )
    evidence_access_token_expire_seconds: int = Field(default=60, ge=10, le=300)
```

Add this validator before `cors_origins`:

```python
    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.app_env.strip().lower() != "production":
            return self

        errors: list[str] = []
        weak_markers = ("replace", "change-this", "cctv_user", "changeme", "example")

        def weak(value: str, *, minimum: int) -> bool:
            normalized = value.strip().lower()
            return len(value.strip()) < minimum or any(
                marker in normalized for marker in weak_markers
            )

        if self.debug:
            errors.append("DEBUG must be false in production")
        if self.jwt_algorithm != "HS256":
            errors.append("JWT_ALGORITHM must be HS256")
        if weak(self.jwt_secret, minimum=32):
            errors.append("JWT_SECRET must be a non-placeholder value of at least 32 characters")
        if weak(self.evidence_signing_secret, minimum=32):
            errors.append(
                "EVIDENCE_SIGNING_SECRET must be a non-placeholder value of at least 32 characters"
            )
        if weak(self.postgres_password, minimum=16):
            errors.append(
                "POSTGRES_PASSWORD must be a non-placeholder value of at least 16 characters"
            )
        if weak(self.api_admin_password, minimum=16):
            errors.append(
                "API_ADMIN_PASSWORD must be a non-placeholder value of at least 16 characters"
            )
        if "*" in self.cors_origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain * in production")
        if self.enable_dr_scheduler and len(self.dr_encryption_passphrase) < 16:
            errors.append(
                "DR_ENCRYPTION_PASSPHRASE must contain at least 16 characters when DR is enabled"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self
```

- [ ] **Step 4: Document the new environment values**

Add after the JWT variables in `.env.example`:

```dotenv
# Separate signing key for short-lived evidence URLs.
# Production requires a random value of at least 32 characters.
EVIDENCE_SIGNING_SECRET=replace_with_a_separate_random_evidence_secret
EVIDENCE_ACCESS_TOKEN_EXPIRE_SECONDS=60
```

Add this production note directly above `APP_ENV`:

```dotenv
# Use production only after replacing every placeholder secret and setting DEBUG=false.
```

- [ ] **Step 5: Run focused and regression tests**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_settings_security.py tests/test_service_container.py -q
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  ruff check app/config/settings.py tests/test_settings_security.py
```

Expected: all focused tests and ruff checks pass.

- [ ] **Step 6: Restrict the local untracked environment file**

Run:

```bash
chmod 600 .env
stat -f '%Sp %N' .env
```

Expected on macOS:

```text
-rw------- .env
```

Do not stage or print `.env`.

- [ ] **Step 7: Commit configuration security**

```bash
git add app/config/settings.py .env.example tests/test_settings_security.py
git commit -m "security: validate production configuration"
```

---

### Task 3: Implement Signed Snapshot Evidence Access

**Files:**

- Create: `app/services/evidence_access_service.py`
- Create: `tests/test_evidence_access_service.py`

**Interfaces:**

- Consumes: snapshot UUID, user UUID, `Settings.storage_path`, and
  `Settings.evidence_signing_secret`.
- Produces:
  - `EvidenceGrant(content_url: str, expires_at: datetime)`;
  - `EvidenceAccessService.issue_snapshot(snapshot_id, user_id)`;
  - `EvidenceAccessService.authorize_snapshot(token, snapshot_id)`;
  - `EvidenceAccessService.resolve_snapshot(snapshot)`.

- [ ] **Step 1: Write failing token and path tests**

Create `tests/test_evidence_access_service.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.evidence_access_service import EvidenceAccessService


def settings(storage_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage_path=storage_path,
        evidence_signing_secret="evidence-signing-secret-with-at-least-32-characters",
        evidence_access_token_expire_seconds=60,
    )


def test_signed_grant_is_bound_to_snapshot_and_user(tmp_path: Path) -> None:
    service = EvidenceAccessService(settings(tmp_path))
    snapshot_id = uuid4()
    user_id = uuid4()

    grant = service.issue_snapshot(snapshot_id, user_id)
    subject = service.authorize_snapshot(grant.token, snapshot_id)

    assert subject == user_id
    assert str(snapshot_id) in grant.content_url
    with pytest.raises(ValueError, match="not valid for this snapshot"):
        service.authorize_snapshot(grant.token, uuid4())


def test_snapshot_path_must_remain_inside_storage(tmp_path: Path) -> None:
    service = EvidenceAccessService(settings(tmp_path))
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")

    with pytest.raises(FileNotFoundError, match="unavailable"):
        service.resolve_snapshot(SimpleNamespace(image_path=str(outside)))


def test_snapshot_path_resolves_jpeg_inside_storage(tmp_path: Path) -> None:
    image = tmp_path / "2026" / "07" / "evidence.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg")
    service = EvidenceAccessService(settings(tmp_path))

    path, media_type = service.resolve_snapshot(
        SimpleNamespace(image_path=str(image))
    )

    assert path == image.resolve()
    assert media_type == "image/jpeg"
```

- [ ] **Step 2: Run the tests and observe import failure**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_evidence_access_service.py -q
```

Expected: test collection fails because
`app.services.evidence_access_service` does not exist.

- [ ] **Step 3: Implement the evidence service**

Create `app/services/evidence_access_service.py`:

```python
"""Short-lived, path-safe access to sensitive snapshot evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt


@dataclass(frozen=True, slots=True)
class EvidenceGrant:
    token: str
    content_url: str
    expires_at: datetime


class EvidenceAccessService:
    algorithm = "HS256"

    def __init__(self, settings: Any) -> None:
        self._storage_root = Path(settings.storage_path).resolve()
        self._secret = settings.evidence_signing_secret
        self._expire_seconds = settings.evidence_access_token_expire_seconds
        if len(self._secret) < 32:
            raise ValueError("Evidence signing secret must contain at least 32 characters")

    def issue_snapshot(self, snapshot_id: UUID, user_id: UUID) -> EvidenceGrant:
        expires_at = datetime.now(UTC) + timedelta(seconds=self._expire_seconds)
        token = jwt.encode(
            {
                "typ": "evidence-access",
                "snapshot_id": str(snapshot_id),
                "sub": str(user_id),
                "jti": str(uuid4()),
                "exp": expires_at,
            },
            self._secret,
            algorithm=self.algorithm,
        )
        return EvidenceGrant(
            token=token,
            content_url=(
                f"/api/v1/evidence/snapshots/{snapshot_id}/content"
                f"?access_token={token}"
            ),
            expires_at=expires_at,
        )

    def authorize_snapshot(self, token: str, snapshot_id: UUID) -> UUID:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self.algorithm])
            if payload.get("typ") != "evidence-access":
                raise ValueError("Evidence token has an invalid purpose")
            if payload.get("snapshot_id") != str(snapshot_id):
                raise ValueError("Evidence token is not valid for this snapshot")
            return UUID(payload["sub"])
        except jwt.PyJWTError as error:
            raise ValueError("Evidence token is invalid or expired") from error
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ValueError) and str(error).startswith("Evidence token"):
                raise
            raise ValueError("Evidence token payload is invalid") from error

    def resolve_snapshot(self, snapshot: Any) -> tuple[Path, str]:
        raw = Path(snapshot.image_path)
        candidates = (
            [raw.resolve()]
            if raw.is_absolute()
            else [(Path.cwd() / raw).resolve(), (self._storage_root / raw).resolve()]
        )
        path = next(
            (
                candidate
                for candidate in candidates
                if candidate.is_relative_to(self._storage_root) and candidate.is_file()
            ),
            None,
        )
        if path is None:
            raise FileNotFoundError("Snapshot evidence is unavailable")
        suffix = path.suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        if suffix not in media_types:
            raise FileNotFoundError("Snapshot evidence type is not supported")
        return path, media_types[suffix]
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_evidence_access_service.py -q
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  ruff check app/services/evidence_access_service.py tests/test_evidence_access_service.py
```

Expected: three tests pass and ruff reports no violations.

- [ ] **Step 5: Commit the evidence domain boundary**

```bash
git add app/services/evidence_access_service.py tests/test_evidence_access_service.py
git commit -m "feat: add signed evidence access service"
```

---

### Task 4: Replace Public Storage URLs with Audited Evidence Routes

**Files:**

- Create: `app/api/routes/evidence.py`
- Create: `tests/test_evidence_routes.py`
- Modify: `app/api/router.py`
- Modify: `app/api/schemas.py`
- Modify: `app/repository/event_repository.py`
- Modify: `app/api/routes/events.py`
- Modify: `app/repository/pipeline_repository.py`
- Modify: `app/services/realtime_pipeline.py`
- Modify: `app/app.py`
- Modify: `tests/test_realtime_pipeline.py`

**Interfaces:**

- Consumes: `EvidenceAccessService`, authenticated `User`, `Snapshot`, and
  `AuditRepository`.
- Produces:
  - `POST /api/v1/evidence/snapshots/{snapshot_id}/access`;
  - `GET /api/v1/evidence/snapshots/{snapshot_id}/content?access_token=...`;
  - `EventResponse.snapshot_id`;
  - WebSocket event payload `snapshot_id`.

- [ ] **Step 1: Write failing route tests**

Create `tests/test_evidence_routes.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_app_settings, get_database_session
from app.api.routes.evidence import router
from app.api.security import require_authenticated_user
from app.models import Snapshot, User


class FakeSession:
    def __init__(self, snapshot: object, user: object) -> None:
        self.snapshot = snapshot
        self.user = user
        self.added: list[object] = []
        self.commits = 0

    async def get(self, model: type, identifier: object) -> object | None:
        if model is Snapshot and identifier == self.snapshot.id:
            return self.snapshot
        if model is User and identifier == self.user.id:
            return self.user
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def refresh(self, value: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def make_client(tmp_path: Path) -> tuple[TestClient, FakeSession, object]:
    image = tmp_path / "snapshot.jpg"
    image.write_bytes(b"snapshot-bytes")
    snapshot = SimpleNamespace(id=uuid4(), image_path=str(image))
    user = SimpleNamespace(id=uuid4(), is_active=True)
    session = FakeSession(snapshot, user)
    settings = SimpleNamespace(
        storage_path=tmp_path,
        evidence_signing_secret="evidence-signing-secret-with-at-least-32-characters",
        evidence_access_token_expire_seconds=60,
    )

    async def database_override():
        yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = database_override
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[require_authenticated_user] = lambda: user
    return TestClient(app), session, snapshot


def test_grant_and_content_are_audited(tmp_path: Path) -> None:
    client, session, snapshot = make_client(tmp_path)

    grant = client.post(f"/evidence/snapshots/{snapshot.id}/access")
    assert grant.status_code == 200

    content = client.get(grant.json()["content_url"])
    assert content.status_code == 200
    assert content.content == b"snapshot-bytes"
    assert content.headers["cache-control"] == "private, no-store"
    assert [item.action for item in session.added] == [
        "EVIDENCE_ACCESS_GRANTED",
        "EVIDENCE_SNAPSHOT_VIEWED",
    ]


def test_content_rejects_invalid_signed_token(tmp_path: Path) -> None:
    client, _, snapshot = make_client(tmp_path)

    response = client.get(
        f"/evidence/snapshots/{snapshot.id}/content?access_token=invalid"
    )

    assert response.status_code == 401
```

Append to the same file:

```python
def test_application_has_no_public_storage_mount(monkeypatch, tmp_path: Path) -> None:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-password")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("API_ADMIN_PASSWORD", "test-admin-password")
    from app.app import create_app

    application = create_app()

    assert all(route.path != "/storage" for route in application.routes)
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the tests and observe failure**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_evidence_routes.py -q
```

Expected: collection fails because `app.api.routes.evidence` does not exist.

- [ ] **Step 3: Add evidence API schemas**

Add to `app/api/schemas.py`:

```python
class EvidenceAccessResponse(BaseModel):
    content_url: str
    expires_at: datetime
```

Change `EventResponse` from:

```python
    snapshot_url: str | None = None
```

to:

```python
    snapshot_id: UUID | None = None
```

- [ ] **Step 4: Implement evidence routes**

Create `app/api/routes/evidence.py`:

```python
"""Authenticated and audited access to sensitive CCTV evidence."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database_session
from app.api.schemas import EvidenceAccessResponse
from app.api.security import require_authenticated_user
from app.config.settings import Settings
from app.models import Snapshot, User
from app.repository import AuditRepository
from app.services.evidence_access_service import EvidenceAccessService

router = APIRouter(prefix="/evidence")


@router.post(
    "/snapshots/{snapshot_id}/access",
    response_model=EvidenceAccessResponse,
)
async def create_snapshot_access(
    snapshot_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> EvidenceAccessResponse:
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot evidence not found")
    grant = EvidenceAccessService(settings).issue_snapshot(snapshot.id, actor.id)
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="EVIDENCE_ACCESS_GRANTED",
        resource_type="snapshot",
        resource_id=str(snapshot.id),
        details={"expires_at": grant.expires_at.isoformat()},
    )
    await session.commit()
    return EvidenceAccessResponse(
        content_url=grant.content_url,
        expires_at=grant.expires_at,
    )


@router.get("/snapshots/{snapshot_id}/content")
async def read_snapshot_content(
    snapshot_id: UUID,
    access_token: str = Query(min_length=1),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    service = EvidenceAccessService(settings)
    try:
        user_id = service.authorize_snapshot(access_token, snapshot_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Evidence user session is invalid")
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot evidence not found")
    try:
        path, media_type = service.resolve_snapshot(snapshot)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    await AuditRepository(session).record(
        actor_user_id=user.id,
        action="EVIDENCE_SNAPSHOT_VIEWED",
        resource_type="snapshot",
        resource_id=str(snapshot.id),
    )
    await session.commit()
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
```

- [ ] **Step 5: Register the evidence router**

Add to `app/api/router.py`:

```python
from app.api.routes.evidence import router as evidence_router
```

Add before the WebSocket registration:

```python
api_router.include_router(evidence_router, tags=["evidence"])
```

- [ ] **Step 6: Return snapshot IDs from event queries**

In `app/repository/event_repository.py`, change the return type of
`list_filtered` to:

```python
    ) -> tuple[list[tuple[Event, UUID | None, UUID, str, str | None, int]], int]:
```

Change:

```python
                Snapshot.image_path,
```

to:

```python
                Snapshot.id,
```

Replace `app/api/routes/events.py` with:

```python
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_event_repository
from app.api.schemas import EventResponse, Page
from app.api.security import require_authenticated_user
from app.repository import EventRepository

router = APIRouter(prefix="/events", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[EventResponse])
async def list_events(
    camera_id: UUID | None = None,
    event_type: str | None = Query(default=None, pattern="^(ENTER|EXIT)$"),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: EventRepository = Depends(get_event_repository),
) -> Page[EventResponse]:
    items, total = await repository.list_filtered(
        camera_id=camera_id,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
    )
    responses = [
        EventResponse(
            id=event.id,
            tracking_id=event.tracking_id,
            byte_track_id=byte_track_id,
            event_type=event.event_type.value,
            line_id=event.line_id,
            centroid=event.centroid,
            occurred_at=event.occurred_at,
            snapshot_id=snapshot_id,
            camera_id=event_camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
        )
        for (
            event,
            snapshot_id,
            event_camera_id,
            camera_name,
            camera_location,
            byte_track_id,
        ) in items
    ]
    return Page[EventResponse](
        items=responses,
        total=total,
        offset=offset,
        limit=limit,
    )
```

- [ ] **Step 7: Publish snapshot IDs from realtime persistence**

In `app/repository/pipeline_repository.py`, replace the successful payload field:

```python
                "snapshot_path": str(snapshot.image_path) if snapshot else None,
```

with:

```python
                "snapshot_id": str(snapshot.snapshot_id) if snapshot else None,
```

In `app/services/realtime_pipeline.py`, delete the unused `Path` import, delete
the `_snapshot_url` method, and replace:

```python
        payload["snapshot_url"] = self._snapshot_url(pending.snapshot)
        return payload
```

with:

```python
        return payload
```

Update assertions in `tests/test_realtime_pipeline.py` so successful event
payloads assert `snapshot_id` and never assert `snapshot_url` or
`snapshot_path`.

- [ ] **Step 8: Remove the public static storage mount**

In `app/app.py`, delete:

```python
from fastapi.staticfiles import StaticFiles
```

Delete:

```python
    application.mount("/storage", StaticFiles(directory=str(settings.storage_path)), name="storage")
```

Do not delete or move the root `storage/` directory.

- [ ] **Step 9: Run evidence, API, and pipeline tests**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  pytest tests/test_evidence_access_service.py \
         tests/test_evidence_routes.py \
         tests/test_realtime_pipeline.py \
         tests/test_snapshot_service.py -q
docker run --rm -v "$PWD:/workspace" -w /workspace cctv-api-test \
  ruff check app tests/test_evidence_access_service.py tests/test_evidence_routes.py
```

Expected: all focused tests pass and ruff reports no violations.

- [ ] **Step 10: Commit the backend evidence boundary**

```bash
git add app/api/routes/evidence.py app/api/router.py app/api/schemas.py \
  app/repository/event_repository.py app/api/routes/events.py \
  app/repository/pipeline_repository.py app/services/realtime_pipeline.py \
  app/app.py tests/test_evidence_routes.py tests/test_realtime_pipeline.py
git commit -m "security: protect snapshot evidence access"
```

---

### Task 5: Update Dashboard Snapshot Preview to Use Signed Access

**Files:**

- Modify: `dashboard/src/api.js`
- Modify: `dashboard/src/App.jsx`

**Interfaces:**

- Consumes: `EventResponse.snapshot_id` and
  `POST /evidence/snapshots/{snapshot_id}/access`.
- Produces: `requestSnapshotUrl(snapshotId, token)` and authenticated preview
  behavior.

- [ ] **Step 1: Add the signed snapshot API helper**

Append to `dashboard/src/api.js`:

```javascript
export async function requestSnapshotUrl(snapshotId, token) {
  if (!snapshotId) throw new Error('Snapshot tidak tersedia')
  const grant = await api(`/evidence/snapshots/${snapshotId}/access`, token, {
    method: 'POST',
  })
  return new URL(grant.content_url, API_BASE).toString()
}
```

- [ ] **Step 2: Replace direct snapshot URL usage**

Change the import in `dashboard/src/App.jsx` from:

```javascript
import { API_BASE, api, login } from './api'
```

to:

```javascript
import { api, login, requestSnapshotUrl } from './api'
```

Delete:

```javascript
  const snapshotUrl = value => value ? `${API_BASE.replace(/\/api\/v1$/, '')}${value}` : null
```

Add after `canAdminister`:

```javascript
  const openSnapshot = useCallback(async snapshotId => {
    if (!snapshotId) return
    try {
      setSnapshot(await requestSnapshotUrl(snapshotId, token))
    } catch (err) {
      setError(err.message)
    }
  }, [token])
```

In `EventHistory`, replace:

```javascript
                onClick={() => onSnapshot(event.snapshot_url)}
                disabled={!event.snapshot_url}
```

with:

```javascript
                onClick={() => onSnapshot(event.snapshot_id)}
                disabled={!event.snapshot_id}
```

In command palette event actions, replace:

```javascript
          if (event.snapshot_url) setSnapshot(snapshotUrl(event.snapshot_url))
```

with:

```javascript
          if (event.snapshot_id) openSnapshot(event.snapshot_id)
```

Add `openSnapshot` to the `commandItems` dependency array.

Replace the `EventHistory` prop:

```javascript
          onSnapshot={value => setSnapshot(snapshotUrl(value))}
```

with:

```javascript
          onSnapshot={openSnapshot}
```

- [ ] **Step 3: Prove that public storage references are gone**

Run:

```bash
! rg -n 'snapshot_url|/storage/' dashboard/src app/api app/services app/repository \
  -g '*.js' -g '*.jsx' -g '*.py'
```

Run the frontend build through Compose so it does not depend on host Node.js:

```bash
docker compose build dashboard
docker compose run --rm --no-deps dashboard npm run build
```

Expected: no public storage reference is found and Vite production build exits
successfully.

- [ ] **Step 4: Commit dashboard compatibility**

```bash
git add dashboard/src/api.js dashboard/src/App.jsx
git commit -m "fix: use signed snapshot previews"
```

---

### Task 6: Remove Only Proven Dead Source

**Files:**

- Delete: `app/ai/__init__.py`
- Delete: `app/repository/tracking_repository.py`
- Modify: `app/repository/__init__.py`

**Interfaces:**

- Consumes: complete import/reference search and the Python 3.12 test image.
- Produces: repository exports without `TrackingRepository`; no replacement
  abstraction.

- [ ] **Step 1: Reconfirm exact references**

Run:

```bash
rg -n 'app\.ai|from app import ai|import app\.ai' app tests examples alembic || true
rg -n 'TrackingRepository' app tests examples alembic
```

Expected:

- no `app.ai` consumer;
- `TrackingRepository` appears only in
  `app/repository/tracking_repository.py` and `app/repository/__init__.py`.

If another consumer appears, classify the component as REVIEW and skip its
deletion.

- [ ] **Step 2: Remove the dead package and repository**

Delete `app/ai/__init__.py`.

Delete `app/repository/tracking_repository.py`.

Replace `app/repository/__init__.py` with:

```python
"""Async repository implementations."""

from app.repository.audit_repository import AuditRepository
from app.repository.backup_repository import BackupRepository
from app.repository.camera_repository import CameraRepository
from app.repository.camera_runtime_repository import CameraRuntimeRepository
from app.repository.disaster_recovery_repository import DisasterRecoveryRepository
from app.repository.event_repository import EventRepository
from app.repository.person_repository import PersonRepository
from app.repository.pipeline_repository import PipelineRepository
from app.repository.snapshot_repository import SnapshotRepository
from app.repository.statistics_repository import StatisticsRepository
from app.repository.user_repository import UserRepository

__all__ = [
    "AuditRepository",
    "BackupRepository",
    "CameraRepository",
    "CameraRuntimeRepository",
    "DisasterRecoveryRepository",
    "EventRepository",
    "PersonRepository",
    "PipelineRepository",
    "SnapshotRepository",
    "StatisticsRepository",
    "UserRepository",
]
```

- [ ] **Step 3: Verify import and test behavior**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test python -c \
  "import app.app; import app.repository; import app.storage"
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
```

Expected: imports succeed, tests have zero failures, and ruff has zero
violations.

- [ ] **Step 4: Commit proven dead-code removal**

```bash
git add app/ai/__init__.py app/repository/tracking_repository.py \
  app/repository/__init__.py
git commit -m "refactor: remove proven dead modules"
```

Do not remove `app/main.py`, `.hallmark`, any migration, or anything under root
`storage/` in this plan.

Ignored local caches (`.pytest_cache`, `.ruff_cache`, `__pycache__`, and
`.DS_Store`) are excluded from Git and Docker. Do not use a broad cleanup
command such as `git clean -x`: it could also remove `.env` or runtime evidence.
Physical cache removal is optional and must target an exact inspected path.

---

### Task 7: Record Cleanup Evidence and Run the Phase 0 Gate

**Files:**

- Create: `docs/audits/2026-07-23-phase0-cleanup-report.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: commits and verification output from Tasks 1–6.
- Produces: permanent cleanup record and an operational security note.

- [ ] **Step 1: Add an operational security warning to README**

Add this section after the Docker startup instructions in `README.md`:

```markdown
## Security baseline

- Never expose the API or dashboard directly to the internet without TLS and an approved reverse proxy.
- Production startup rejects placeholder database, JWT, administrator, and evidence-signing secrets.
- Keep `.env` outside Git with file permission `0600`; production secrets belong in the deployment secret manager.
- Snapshot evidence is not public static content. The dashboard requests a short-lived signed URL, and every grant/view is audited.
- Do not delete `storage/`, PostgreSQL volumes, or historical Alembic migrations during source cleanup.
```

- [ ] **Step 2: Run the complete backend gate**

Run:

```bash
docker build --target test -t cctv-api-test .
docker run --rm cctv-api-test python --version
docker run --rm cctv-api-test pytest -q
docker run --rm cctv-api-test ruff check app tests alembic examples
```

Expected:

- Python reports `3.12.x`;
- pytest has zero failures;
- ruff has zero violations.

- [ ] **Step 3: Run migration verification on a disposable database**

Start only the project PostgreSQL container:

```bash
docker compose up -d postgres
docker compose ps postgres
```

Expected: PostgreSQL status is healthy.

Create and migrate a disposable verification database. Resolve
`POSTGRES_USER` inside the container so the command does not depend on exported
host-shell variables:

```bash
docker compose exec -T postgres sh -lc \
  'createdb -U "$POSTGRES_USER" cctv_phase0_verify'
docker compose run --rm \
  -e POSTGRES_DB=cctv_phase0_verify \
  api alembic upgrade head
docker compose exec -T postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d cctv_phase0_verify -tAc "SELECT version_num FROM alembic_version"'
```

Expected:

```text
0009_presence_sessions
```

Drop only the explicitly named disposable database after validation:

```bash
docker compose exec -T postgres sh -lc \
  'dropdb -U "$POSTGRES_USER" cctv_phase0_verify'
```

- [ ] **Step 4: Run production image and dashboard gates**

Run:

```bash
docker compose build api dashboard
docker compose run --rm --no-deps dashboard npm run build
docker compose config --quiet
git diff --check
! rg -n 'snapshot_url|/storage/' dashboard/src app/api app/services app/repository \
  -g '*.js' -g '*.jsx' -g '*.py'
```

Expected: both images build, the Vite production build succeeds, Compose config
is valid, Git reports no whitespace errors, and no public snapshot URL remains.

- [ ] **Step 5: Create the cleanup report from confirmed results**

Create `docs/audits/2026-07-23-phase0-cleanup-report.md`:

```markdown
# Phase 0 Cleanup Report

**Date:** 2026-07-23
**Branch:** `cctv/versi-1`
**Scope:** Source reproducibility, production configuration, snapshot evidence access, and proven dead code.

## Preserved

- All Alembic migrations from `0001_initial_schema` through `0009_presence_sessions`.
- Root `storage/` evidence and backup archives.
- PostgreSQL data and Docker volume.
- `app/main.py` compatibility entry point.
- `.hallmark` design metadata pending a separate review.
- Existing realtime pipeline, presence reconciliation, and occupancy behavior pending replacement phases.

## Removed

| Path | Evidence | Impact |
|---|---|---|
| `app/ai/__init__.py` | No imports or runtime references | Removes an empty package only |
| `app/repository/tracking_repository.py` | Referenced only by its package export | Removes an unused repository; pipeline persistence remains in `PipelineRepository` |

## Repaired

- Root storage ignore patterns no longer hide `app/storage`.
- Snapshot service source is tracked and included in clean Docker builds.
- Production configuration rejects weak secrets and unsafe debug/CORS/JWT settings.
- Snapshot evidence is accessed through short-lived signed URLs.
- Evidence grants and content views are written to `audit_logs`.
- The unauthenticated `/storage` static mount is removed.

## Verification Gate

- Python version in the test image: 3.12.
- Backend pytest suite: zero failures.
- Ruff: zero violations.
- API production image: build successful.
- Dashboard production build: successful.
- Alembic upgrade to `0009_presence_sessions`: successful on a disposable PostgreSQL database.
- Public `/storage` route: absent.
- Worktree after final commit: clean.

## Deferred

- Capture-first asynchronous jobs.
- Building, zone, camera topology, and transition entities.
- Face/periocular candidate selection.
- Global journey and occupancy replacement.
- Policy engine, alerts, and target role model.
```

- [ ] **Step 6: Commit the Phase 0 report**

```bash
git add docs/audits/2026-07-23-phase0-cleanup-report.md README.md
git commit -m "docs: record Phase 0 cleanup evidence"
```

- [ ] **Step 7: Verify final repository state**

Run:

```bash
git status --short --branch
git log --oneline -7
```

Expected:

- the branch is `cctv/versi-1`;
- the worktree has no unstaged or uncommitted files;
- Tasks 1–7 appear as small, reviewable commits.

---

## Plan Self-Review

### Specification coverage

- Source-control risk for `app/storage`: Task 1.
- Python 3.12 test/build baseline: Tasks 1 and 7.
- Weak secret and environment-file posture: Task 2.
- Public evidence route and missing audit: Tasks 3–5.
- Dead-code removal with reference proof: Task 6.
- Migration/evidence preservation and cleanup documentation: Task 7.

Architectural replacement of realtime processing, occupancy, topology, identity,
and policy is intentionally excluded. Those items require separate specs and
plans after this gate passes.

### Interface consistency

- Backend events expose `snapshot_id`.
- Realtime event payloads expose `snapshot_id`.
- Dashboard requests access using the same `snapshot_id`.
- Evidence grants expose `content_url` and `expires_at`.
- Evidence content tokens are bound to both snapshot and user.

### Safety boundary

This plan removes only two tracked source files after a fresh reference search.
It never deletes root `storage/`, Docker volumes, `.env`, Alembic migrations,
`app/main.py`, or `.hallmark`.
