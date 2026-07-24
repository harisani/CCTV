# Phase 1 Application Foundation Design

**Date:** 2026-07-24  
**Branch:** `cctv/versi-1`  
**Status:** Approved design  
**Deployment target:** One Linux server running Docker Compose

## 1. Purpose

Phase 1 strengthens the application, database, configuration, logging, error
handling, and container foundations without changing the existing CCTV
business behavior.

The phase is compatibility-first. Existing API clients, the React dashboard,
camera runtime, event payloads, occupancy calculations, and role model must
continue to work while the operational foundation becomes safer and easier to
diagnose.

## 2. Approved Decisions

- Preserve the current roles and permissions. The target six-role model is
  deferred to a later phase.
- Run one API instance during the pilot.
- Do not add Redis, Kubernetes, a metrics stack, or another infrastructure
  service in this phase.
- Keep all existing API and dashboard contracts compatible.
- Continue deploying API, PostgreSQL, and dashboard with Docker Compose on one
  Linux server.
- Use an incremental foundation hardening approach rather than a broad
  application rewrite.

## 3. Scope

### In scope

- Per-request and per-WebSocket correlation IDs.
- Structured application and request logging.
- Sensitive-value redaction rules.
- Predictable asynchronous database transaction behavior.
- Liveness, readiness, and legacy health endpoints.
- In-process login rate limiting for a single API instance.
- Safe, consistent error responses.
- Non-root API container execution.
- Docker Compose health checks, dependency health, restart behavior, and
  graceful shutdown.
- Unit, integration, regression, migration, build, and Docker verification.
- Phase 1 operational documentation and rollback notes.

### Out of scope

- New role names or permission redesign.
- Redis or distributed rate limiting.
- Kubernetes or multi-server orchestration.
- OpenTelemetry, Prometheus, Grafana, or a centralized log service.
- Breaking WebSocket authentication changes.
- Buildings, floors, areas, zones, topology, or camera-role entities.
- Capture-first jobs, processing queues, or AI workers.
- Changes to RTSP, YOLO, ByteTrack, ReID, crossing, snapshots, reconciliation,
  or occupancy behavior.
- Dashboard redesign.
- Destructive migrations or deletion of legacy migrations and production data.

## 4. Architecture

The existing application layers remain in place:

```text
HTTP or WebSocket request
    -> request context
    -> authentication and login protection
    -> route
    -> service
    -> repository
    -> async database session
    -> PostgreSQL
```

Foundation behavior stays at the application edge. Business services do not
become dependent on FastAPI request objects.

### Request context

A request-context component owns the correlation ID for the lifetime of an
HTTP request or WebSocket connection. It uses context-local storage so
concurrent requests cannot leak identifiers into one another.

For HTTP:

- accept `X-Correlation-ID` only when it matches the documented safe format and
  length;
- generate a UUID when the header is absent or invalid;
- include the effective ID in `X-Correlation-ID` on the response;
- make the ID available to log records and error handlers;
- clear request context in a `finally` path.

For WebSocket:

- create a server-side connection correlation ID;
- use it for connection, authentication failure, disconnect, and unexpected
  error logs;
- preserve the existing dashboard authentication contract;
- never log the JWT or the full WebSocket URL when it contains credentials.

## 5. Logging

Production logging is structured JSON on standard output. Development and test
logging remains concise and human-readable.

Common structured fields are:

- timestamp;
- level;
- logger;
- message;
- correlation ID;
- HTTP method and normalized path when applicable;
- status code and request duration;
- authenticated user ID when already available;
- exception type for failures.

Logs must not contain:

- passwords;
- JWTs or evidence bearer tokens;
- authorization headers;
- RTSP usernames, passwords, or complete credential-bearing URLs;
- database passwords or complete connection URLs;
- DR encryption passphrases;
- raw biometric embeddings;
- unrestricted filesystem paths for evidence;
- request bodies from authentication or sensitive upload endpoints.

The access log records a normalized path, not an uncontrolled raw request
target. Existing application log calls remain valid through the standard
Python logging API.

## 6. Database Session and Transaction Behavior

Each HTTP request receives one `AsyncSession`, which is always closed.

Transaction rules:

- read-only operations do not commit;
- a successful write commits at the service or use-case boundary;
- a failed operation rolls back before the session is released;
- a session is never reused after an unhandled database error;
- repositories continue to express persistence operations and do not create
  independent process-wide sessions;
- existing durability-sensitive audit flows, including evidence grant and view
  audits, retain their explicit commit behavior;
- no mass repository rewrite is performed in Phase 1.

Tests must prove rollback behavior with a real transaction boundary. Existing
write paths are changed only when an ambiguity or missing rollback is
demonstrated by a failing regression test.

## 7. Health Model

Three compatible endpoints are provided:

### `GET /health/live`

- proves the API process and event loop can answer;
- does not query PostgreSQL or external services;
- returns success while a dependency is temporarily unavailable.

### `GET /health/ready`

- verifies PostgreSQL connectivity with a bounded, lightweight query;
- verifies that application startup has completed;
- returns `503` when the application should not receive traffic;
- does not expose connection strings, hosts, credentials, SQL, or stack traces.

### `GET /health`

- remains registered for existing dashboard and deployment compatibility;
- preserves its current successful response contract;
- may include safe high-level readiness information only when this does not
  break existing clients.

Readiness does not load AI models or open every camera. Camera health remains a
separate business/runtime concern and cannot prevent API administration access.

## 8. Login Rate Limiting

The login endpoint receives an in-process limiter suitable for the approved
single API instance.

- The key combines a normalized username and trusted client address.
- Failed authentication increments the limiter.
- Successful authentication clears the matching limiter state.
- Entries expire automatically after the configured window.
- A blocked attempt returns HTTP `429` and a safe `Retry-After` header.
- The limiter stores neither passwords nor tokens.
- Memory usage is bounded through expiry cleanup and a configured maximum entry
  count.
- Existing persistent user lockout remains active as a separate defense.

The limitation is documented: running more than one API replica requires a
shared rate-limit backend in a later phase.

## 9. Error Contract

Error responses keep the existing `detail` field and add the effective
`correlation_id` where a request context exists.

Status behavior remains:

- validation failure: `422`;
- authentication failure: `401`;
- authorization failure: `403`;
- missing resource: `404`;
- data conflict: `409`;
- rate limit: `429`;
- unavailable database/readiness: `503`;
- unexpected application failure: `500`.

Database details, SQL, stack traces, credentials, internal paths, and model
internals are never returned to clients. Full exceptions are recorded only in
protected server logs with sensitive-value controls.

## 10. Dependency Injection and Lifecycle

FastAPI remains the composition edge:

- settings are supplied through the existing settings dependency;
- request database sessions are supplied through one dependency;
- long-lived services remain owned by the application lifespan/service
  container;
- middleware owns request context but not business logic;
- login rate limiting is exposed behind an interface so a distributed backend
  can replace it later without changing the login route contract.

Startup order remains compatible with the existing runtime. Shutdown stops
background services before disposing the SQLAlchemy engine.

## 11. Docker and Deployment

The production API image:

- uses the existing Python 3.12 production stage;
- creates and runs as a dedicated non-root application user;
- retains write access only to required runtime locations such as the mounted
  storage directory;
- keeps source and configuration read-only where practical;
- responds correctly to the container stop signal for graceful shutdown.

Docker Compose:

- retains PostgreSQL, API, and dashboard services;
- uses PostgreSQL health for API dependency ordering;
- uses API readiness for API health;
- uses `unless-stopped` restart behavior;
- does not add Redis or another platform service;
- does not impose CPU/GPU resource limits until the pilot server profile is
  approved.

Production TLS termination and external secret injection remain deployment
responsibilities. Environment-file development compatibility remains, while
production continues to require non-placeholder secrets and protected secret
storage established in Phase 0.

## 12. Compatibility Requirements

Phase 1 must not change:

- current public endpoint paths;
- successful response fields consumed by the dashboard;
- current role values or authorization meaning;
- current WebSocket message shapes;
- snapshot evidence authorization behavior;
- event direction and crossing behavior;
- occupancy counters or reconciliation;
- camera runtime enablement and stream behavior;
- persisted business records.

Additive headers and new health endpoints are permitted. Any discovered
incompatible behavior stops implementation until it has a compatibility design
and explicit approval.

## 13. Testing Strategy

### Unit tests

- correlation ID validation and generation;
- request-context isolation and cleanup;
- structured log fields;
- sensitive-value redaction;
- login limiter failure count, block, expiry, reset, and key isolation;
- safe exception mapping.

### Integration tests

- database session closes and rolls back after failure;
- readiness succeeds with PostgreSQL and returns `503` without it;
- liveness remains successful during database failure;
- correlation ID is present in response headers, error responses, and logs;
- login rate limiting and persistent lockout coexist;
- legacy health and authentication contracts remain compatible.

### Regression tests

- authentication and existing roles;
- evidence grant, retrieval, revocation, and audit;
- camera, event, snapshot, person, and statistics endpoints;
- dashboard WebSocket behavior;
- current camera runtime and pipeline tests.

### Deployment verification

- Python 3.12 test image;
- complete pytest suite;
- Ruff;
- Alembic upgrade to the current head on a disposable PostgreSQL database;
- API and dashboard image builds;
- dashboard unit tests and Vite production build;
- Docker Compose configuration validation and startup;
- runtime proof that the API process is non-root;
- liveness, readiness, dependency failure, and graceful shutdown checks.

## 14. Implementation Sequence

1. Add request context and correlation-ID tests.
2. Add environment-aware structured logging and redaction tests.
3. Prove and harden database rollback/session behavior.
4. Add health service plus live, ready, and compatibility routes.
5. Add the bounded in-process login limiter.
6. Add correlation-aware safe error responses.
7. Harden the API image and Docker Compose health/restart configuration.
8. Run complete regression, migration, build, and runtime verification.
9. Publish a Phase 1 report with changed files, decisions, test evidence,
   compatibility results, rollback notes, and deferred work.

Each step follows red-green-refactor and ends in an independently reviewable
commit.

## 15. Acceptance Criteria

Phase 1 is complete only when:

- all backend and dashboard tests pass;
- Ruff and build checks pass;
- Alembic upgrades a disposable database to the current head;
- existing API and dashboard contracts remain compatible;
- every HTTP response has an effective correlation ID;
- production logs are valid structured records and contain no tested sensitive
  values;
- transaction failures roll back and release their sessions;
- liveness and readiness behave correctly during database availability and
  failure;
- login limiting returns `429` at the configured boundary and resets correctly;
- API and dashboard start through Docker Compose;
- the API process runs as non-root;
- no destructive migration, production-data change, or unrelated CCTV behavior
  change occurs;
- independent review reports no unresolved Critical or Important issue.

## 16. Risks and Trade-offs

### In-memory limiter

It is intentionally simple and appropriate only for one API instance. Its state
is lost on restart and is not shared across replicas. Existing persistent
account lockout remains the durable protection. A shared backend is required
before horizontal API scaling.

### Compatibility-first transactions

Avoiding a mass repository rewrite lowers regression risk but leaves some
historical transaction styles in place. Phase 1 corrects demonstrated
ambiguities and establishes the rule for new work.

### Logging without a centralized platform

JSON standard output is machine-readable and deployment-neutral, but searching,
retention, and alerting depend on the server's log collection policy until a
central observability platform is approved.

### Readiness scope

Readiness checks PostgreSQL and application startup only. It deliberately does
not require all cameras or AI models to be online, allowing administrators to
diagnose partial CCTV outages through the API.

## 17. Deferred Work

- Six-role least-privilege redesign.
- Shared/distributed rate limiting.
- WebSocket authentication transport redesign.
- Central metrics, traces, and log aggregation.
- Deployment-specific TLS and network segmentation automation.
- CPU/GPU resource limits based on pilot measurements.
- Building/zone/topology data model and every later functional phase.
