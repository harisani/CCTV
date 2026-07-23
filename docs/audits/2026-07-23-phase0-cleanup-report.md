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

- Python version in the test image: 3.12.13.
- Backend pytest suite: 67 passed, zero failures.
- Ruff: zero violations.
- API production image: build successful.
- Dashboard production build: successful.
- Alembic upgrade to `0009_presence_sessions`: successful on the disposable `cctv_phase0_verify` PostgreSQL database.
- Disposable verification database: removed after validation.
- Public `/storage` route: absent.
- Worktree after final commit: clean.

## Deferred

- Capture-first asynchronous jobs.
- Building, zone, camera topology, and transition entities.
- Face/periocular candidate selection.
- Global journey and occupancy replacement.
- Policy engine, alerts, and target role model.
