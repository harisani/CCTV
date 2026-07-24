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
- Application environments are normalized and constrained to `development`,
  `test`, or `production`; unknown values fail closed.
- Production configuration rejects weak secrets, identical JWT/evidence keys,
  and unsafe debug/CORS/JWT settings.
- Snapshot evidence grants return a clean content URL and a separate
  short-lived credential. The dashboard sends that credential only as a Bearer
  header, fetches a Blob, and renders a revocable in-memory object URL.
- Evidence credentials are bound to the issuing user's `token_version`, so
  deactivation and session-version changes revoke outstanding grants.
- Evidence grants and content views are written to `audit_logs` with the same
  non-secret grant ID for correlation.
- Authenticated snapshot lists expose stable IDs, bounding boxes, and
  timestamps without serializing internal image or metadata filesystem paths.
- The unauthenticated `/storage` static mount is removed.

## Verification Gate at Phase 0 Baseline

The following results describe baseline commit `0fad5af` before the final
security-review fix wave:

- Python version in the test image: 3.12.13.
- Backend pytest suite: 67 passed, zero failures at that baseline.
- Ruff: zero violations.
- API production image: build successful.
- Dashboard production build: successful.
- Alembic upgrade to `0009_presence_sessions`: successful on the disposable `cctv_phase0_verify` PostgreSQL database.
- Disposable verification database: removed after validation.
- Public `/storage` route: absent.
- Worktree after baseline commit: clean.

## Final Security Review Gate

The 2026-07-24 final-review fix wave preserved the baseline scope and passed a
fresh verification gate:

- Backend pytest suite: 82 passed in 1.94 seconds.
- Ruff 0.15.22: `All checks passed!`.
- API and dashboard Compose images: build successful.
- Dashboard lifecycle and transport tests: 6 passed in 84.104 milliseconds.
- Dashboard production build: 952 modules transformed and build successful in
  2.23 seconds; the existing bundle-size advisory remains non-failing.
- Docker Compose configuration: valid.
- Git whitespace validation: clean.
- Source scan: no evidence token in a query URL, no `snapshot_url`, and no
  public `/storage/` reference in dashboard/API/service/repository source.
- Public snapshot contract scan: no `image_path` or `metadata_path` field in
  the snapshot route or API response schema.

## Final Re-review Addendum Gate

A final 2026-07-24 contract re-review found and removed two internal
filesystem fields from authenticated snapshot-list serialization. The
follow-up gate passed:

- Backend pytest suite: 83 passed in 1.97 seconds.
- Ruff 0.15.22: `All checks passed!`.
- API and dashboard Compose images: build successful.
- Dashboard lifecycle and transport tests: 6 passed in 98.983459 milliseconds.
- Dashboard production build: 952 modules transformed and build successful in
  2.36 seconds; the same bundle-size advisory remains non-failing.
- Docker Compose configuration and Git whitespace validation: clean.
- Credential/public-storage scan and the dedicated public snapshot path-field
  scan: no matches.

## Deferred

- Capture-first asynchronous jobs.
- Building, zone, camera topology, and transition entities.
- Face/periocular candidate selection.
- Global journey and occupancy replacement.
- Policy engine, alerts, and target role model.
