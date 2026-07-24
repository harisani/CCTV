# Phase 1 Application Foundation Report

Date: 2026-07-24  
Branch: `cctv/versi-1`  
Design baseline: `80cc2f9`  
Implementation-plan baseline: `090e016`  
Verified implementation head: `02e07db`

## Scope

Phase 1 hardens the existing application foundation without replacing its CCTV
business flow. The delivered scope is:

- request correlation for HTTP and dashboard WebSocket operations;
- environment-aware text/JSON logging with credential redaction;
- explicit rollback and close behavior for request-scoped async sessions;
- liveness, readiness, and backward-compatible health endpoints;
- bounded single-process failed-login rate limiting;
- safe correlated HTTP and WebSocket error responses;
- non-root production containers, health checks, restart policy, and writable
  snapshot storage;
- bounded OpenCV open/read operations and graceful camera shutdown;
- full migration, test, build, outage, recovery, and runtime verification.

No database migration, third-party dependency, role redesign, endpoint removal,
or intentional CCTV pipeline behavior change was included.

## Approved Compatibility Boundaries

- The existing role enum and permission mappings are unchanged.
- Successful API response bodies and dashboard WebSocket payloads retain their
  existing fields.
- `GET /api/v1/health` remains available while `/health/live` and
  `/health/ready` provide deployment-specific semantics.
- Readiness depends on application startup and PostgreSQL, not on every camera
  or AI model being online.
- The login limiter is deliberately process-local because Phase 1 supports one
  API instance.
- Existing repository transaction ownership remains compatible; the request
  session boundary now guarantees rollback on propagated failures.

## Commits

| Commit | Responsibility |
| --- | --- |
| `6775d0c` | Request correlation context and middleware |
| `780725a` | Structured application logging |
| `7863679` | First logging-redaction hardening |
| `8fed3b2` | Exact sensitive-key redaction |
| `0f24ece` | Sensitive logging key-suffix redaction |
| `06c5c18` | Request-session rollback and release |
| `d79f5a5` | Live, ready, and compatible health behavior |
| `969d4da` | Bounded failed-login limiter |
| `2d943c0` | Safe correlated error responses |
| `7622203` | Correlation preservation for unexpected HTTP 500 responses |
| `c2150c2` | Non-root and health-checked production containers |
| `014314d` | Readiness handling for DNS/socket database outages |
| `02e07db` | Bounded camera I/O and graceful container shutdown |

## Changed Files and Responsibilities

- `app/api/request_context.py` owns validated correlation-ID context.
- `app/api/middleware.py` binds correlation IDs, records request completion,
  and returns the effective ID to clients.
- `app/api/error_handlers.py` produces generic, correlated public errors.
- `app/api/routes/dashboard_ws.py` isolates WebSocket correlation context and
  avoids credential leakage.
- `app/api/routes/health.py` and `app/services/health_service.py` separate
  liveness from PostgreSQL-backed readiness.
- `app/api/routes/auth.py`, `app/services/login_rate_limiter.py`, and the
  service container implement the single-instance login boundary.
- `app/database/session.py` owns rollback and close behavior for failed
  request-scoped transactions.
- `app/utils/logging.py` provides structured formatting, context injection,
  and tested redaction.
- `app/services/camera_service.py` bounds native OpenCV open/read calls.
- `app/services/camera_runtime_manager.py` and `app/services/container.py`
  propagate camera timeout configuration while retaining parallel shutdown.
- `Dockerfile` runs production as UID/GID `10001`.
- `docker-compose.yml` defines readiness-based startup, restart policy, and a
  30-second API stop grace period.
- `.env.example` and `README.md` document the new operational settings.
- The Phase 1 test files cover every new public or failure behavior.

The complete diff from `80cc2f9` through `02e07db` changes 32 files with 3,916
insertions and 78 deletions. Most insertions are the implementation plan and
regression tests.

## RED/GREEN Evidence by Task

1. Correlation tests first demonstrated missing generated/client IDs and
   context cleanup. GREEN: 24 focused tests and Ruff passed.
2. Logging fixtures first exposed bearer, RTSP, password, database credential,
   nested-key, and suffix cases. Three review/fix loops ended with 23 focused
   tests and Ruff passing.
3. A failing-session fixture demonstrated ambiguous cleanup. GREEN: 12 selected
   session/error tests and Ruff passed.
4. Health tests first demonstrated the missing live/ready distinction. GREEN:
   11 focused tests and Ruff passed.
5. Limiter tests covered boundary, reset, expiry, identifier isolation, and
   concurrent failures. GREEN: 30 focused/regression tests and Ruff passed.
6. Error tests demonstrated correlation and disclosure failures, including an
   unexpected HTTP 500. GREEN: 19 regression tests and Ruff passed.
7. Container checks demonstrated root execution and incomplete deployment
   health behavior. GREEN: 131 backend tests, six dashboard tests, both image
   builds, UID `10001`, and a writable storage probe passed.
8. Runtime outage testing exposed two acceptance defects. Commit `014314d`
   changed database DNS/socket failures from HTTP 500 to readiness 503. Commit
   `02e07db` reduced failed RTSP open operations from approximately 30 seconds
   to the configured five-second default and changed API stop from exit 137 to
   exit 0. Its focused gate passed 13 tests in 1.40 seconds.

## Full Test and Ruff Results

Executed on the Docker test target based on Python `3.12.13`:

```text
docker run --rm cctv-phase1-test pytest -q
140 passed, 2 warnings in 3.02s
exit 0

docker run --rm cctv-phase1-test ruff check .
All checks passed!
exit 0
```

The two non-blocking warnings are upstream Starlette deprecations concerning
the TestClient HTTP transport and the HTTP 422 constant.

Dashboard verification in the built Node image:

```text
npm test
6 passed, 0 failed

npm run build
952 modules transformed
build completed in 2.48s
```

Vite emitted one non-blocking warning for a 519.55 kB minified JavaScript
chunk. Both the API and dashboard production images built successfully.

## Alembic Disposable-Database Result

A specifically named disposable PostgreSQL database was created, upgraded from
an empty schema, inspected, and removed. Alembic applied revisions `0001`
through `0009` and reported:

```text
0009_presence_sessions (head)
```

The removal check confirmed the disposable database no longer existed. No
production data, volume, or existing migration was changed.

## Docker Build and Runtime Result

`docker compose up -d --build` completed successfully. PostgreSQL, API, and
dashboard reached `healthy`.

Observed health responses:

```text
GET /api/v1/health/live   -> 200
GET /api/v1/health/ready  -> 200
```

During a PostgreSQL-only stop:

```text
live  -> 200
ready -> 503
ready -> 503
ready -> 503
```

After PostgreSQL restart, readiness recovered to 200 on the first retry.

Final `docker compose stop` completed in 4.26 seconds. API, dashboard, and
PostgreSQL all exited with code 0. The API reported `OOMKilled=false`, logged
camera-runtime completion, and logged application shutdown completion.

## Correlation and Logging Security Result

Regression tests verify generated and accepted correlation IDs, invalid-ID
replacement, concurrent context isolation, context cleanup, HTTP response
headers, error bodies, and WebSocket lifecycle isolation.

The final source scans found zero prohibited public snapshot/storage-path
patterns. A runtime fixture passed a synthetic bearer token, RTSP password,
password assignment, and database credential through `redact_sensitive`.
All four secret values were absent from the result.

## Health and Login-Limiter Result

- Liveness is independent of PostgreSQL availability.
- Readiness is 200 only after startup and a successful PostgreSQL probe.
- DNS, socket, connection, and timeout failures return a generic readiness 503.
- Cancellation and programming errors are not hidden by the health probe.
- The existing health route retains its successful compatibility contract.
- Failed logins return 429 at the configured boundary.
- Success resets the identifier bucket.
- Expired attempts are pruned.
- Concurrent attempts cannot bypass the configured bound.
- The process-local limitation is documented and accepted for one API replica.

## Non-root and Storage-Write Result

The API process reported:

```text
uid=10001 gid=10001
storage_write=ok
```

The write probe was removed immediately after verification. The application
source remains read-only in the production image while the mounted storage
directory remains writable.

## Rollback Procedure

Phase 1 can be rolled back without a database downgrade because it adds no
migration:

1. stop the Compose services without removing volumes;
2. deploy the previously approved image or revert Phase 1 commits in reverse
   order;
3. restore the previous environment file while retaining its secrets;
4. rebuild and start the API and dashboard;
5. verify the legacy health endpoint, login, dashboard, and camera runtime.

Do not use `docker compose down -v`; PostgreSQL and evidence volumes must be
preserved. If rolling back only the camera shutdown fix, revert `02e07db` and
remove only the two camera timeout variables that were added for that commit.

## Deferred Work

- Six-role least-privilege redesign; the old roles remain intentionally.
- Shared/distributed rate limiting before multiple API replicas.
- WebSocket authentication transport redesign.
- Central metrics, tracing, searchable log retention, and alerting.
- Dashboard code splitting.
- Multi-server orchestration and Redis-backed shared state.

## Known Non-blocking Concerns

- The limiter resets on API restart and is not shared across replicas.
- Structured logs still depend on the server's external collection and
  retention policy.
- Readiness intentionally does not fail for an offline camera.
- A native camera operation can delay shutdown up to its configured bounded
  timeout, while the 30-second container grace period provides cleanup margin.
- The dashboard production bundle exceeds Vite's default 500 kB advisory
  threshold.
- Two upstream framework deprecation warnings remain in the test output.
