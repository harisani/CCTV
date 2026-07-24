"""Short-lived transactional persistence boundary for realtime workers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    AIJobStatus,
    AIJobType,
    AIProcessingJob,
    CameraZoneMapping,
    CaptureEvent,
    CaptureEventStatus,
    EvidenceAsset,
    EvidenceAssetType,
    EvidenceIntegrityStatus,
    Event,
    EventType,
    PresenceSession,
    PresenceStatus,
    ProcessingPriority,
    Snapshot,
    Tracking,
    VirtualLine,
    Zone,
)
from app.repository.person_repository import PersonRepository
if TYPE_CHECKING:
    from app.services.crossing_service import CrossingEvent
    from app.storage import SnapshotResult
    from app.tracker import TrackedDetection


class PipelineRepository:
    """Keep camera loops independent from long-lived SQLAlchemy sessions."""

    def __init__(
        self,
        session_factory: Any,
        *,
        evidence_retention_days: int = 90,
        ai_job_max_attempts: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._evidence_retention_days = evidence_retention_days
        self._ai_job_max_attempts = ai_job_max_attempts

    async def identify_person(
        self,
        reid_service: Any,
        embedding: tuple[float, ...],
        *,
        quality_score: float,
        camera_id: UUID,
        captured_at: datetime,
    ) -> Any:
        async with self._session_factory() as session:
            return await reid_service.identify_embedding(
                embedding,
                PersonRepository(session),
                quality_score=quality_score,
                camera_id=camera_id,
                captured_at=captured_at,
            )

    async def link_embedding(self, embedding_id: UUID, tracking_id: UUID) -> None:
        async with self._session_factory() as session:
            repository = PersonRepository(session)
            await repository.link_embedding_to_tracking(embedding_id, tracking_id)
            await session.commit()

    async def start_tracking(
        self,
        *,
        camera_id: UUID,
        byte_track_id: int,
        person_id: UUID | None,
        centroid: tuple[float, float],
        started_at: datetime,
    ) -> UUID:
        async with self._session_factory() as session:
            await session.execute(
                update(Tracking)
                .where(
                    Tracking.camera_id == camera_id,
                    Tracking.byte_track_id == byte_track_id,
                    Tracking.is_active.is_(True),
                )
                .values(is_active=False, ended_at=started_at)
            )
            tracking = Tracking(
                id=uuid4(),
                camera_id=camera_id,
                person_id=person_id,
                byte_track_id=byte_track_id,
                started_at=started_at,
                last_centroid={"x": centroid[0], "y": centroid[1]},
                is_active=True,
            )
            session.add(tracking)
            await session.commit()
            return tracking.id

    async def update_trackings(
        self, updates: list[tuple[UUID, tuple[float, float]]]
    ) -> None:
        if not updates:
            return
        async with self._session_factory() as session:
            for tracking_id, centroid in updates:
                await session.execute(
                    update(Tracking)
                    .where(Tracking.id == tracking_id, Tracking.is_active.is_(True))
                    .values(last_centroid={"x": centroid[0], "y": centroid[1]})
                )
            await session.commit()

    async def close_trackings(
        self, tracking_ids: list[UUID], *, ended_at: datetime | None = None
    ) -> None:
        if not tracking_ids:
            return
        async with self._session_factory() as session:
            await session.execute(
                update(Tracking)
                .where(Tracking.id.in_(tracking_ids), Tracking.is_active.is_(True))
                .values(is_active=False, ended_at=ended_at or datetime.now(UTC))
            )
            await session.commit()

    async def close_camera_trackings(self, camera_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Tracking)
                .where(Tracking.camera_id == camera_id, Tracking.is_active.is_(True))
                .values(is_active=False, ended_at=datetime.now(UTC))
            )
            await session.commit()

    async def persist_crossing(
        self,
        *,
        database_tracking_id: UUID,
        person_id: UUID | None,
        crossing: CrossingEvent,
        track: TrackedDetection,
        snapshot: SnapshotResult | None,
        snapshot_error: str | None,
    ) -> tuple[bool, dict[str, Any]]:
        async with self._session_factory() as session:
            existing = await session.get(Event, crossing.event_id)
            if existing is not None:
                return False, {"reason": "already_persisted", "discard_snapshot": False}
            tracking = await session.get(Tracking, database_tracking_id)
            if tracking is None:
                raise ValueError("Tracking row is required for a presence event")
            open_presence = await self._find_open_presence(
                session,
                person_id=person_id,
                database_tracking_id=database_tracking_id,
            )
            crossing_type = EventType(crossing.event_type.value)
            presence_match = "NEW_SESSION" if crossing_type == EventType.ENTER else "IDENTITY"
            if crossing_type == EventType.ENTER and open_presence is not None:
                self._logger_for_transition(
                    "Duplicate ENTER suppressed",
                    crossing=crossing,
                    person_id=person_id,
                )
                return False, {"reason": "duplicate_enter", "discard_snapshot": True}
            if crossing_type == EventType.EXIT and open_presence is None:
                open_presence = await session.scalar(
                    select(PresenceSession)
                    .where(
                        PresenceSession.camera_id == tracking.camera_id,
                        PresenceSession.status.in_((PresenceStatus.ACTIVE, PresenceStatus.UNCERTAIN)),
                    )
                    .order_by(PresenceSession.entered_at)
                    .with_for_update()
                )
                presence_match = "CAMERA_FIFO"
            if crossing_type == EventType.EXIT and open_presence is None:
                self._logger_for_transition(
                    "Orphan EXIT suppressed",
                    crossing=crossing,
                    person_id=person_id,
                )
                return False, {"reason": "orphan_exit", "discard_snapshot": True}
            event = Event(
                id=crossing.event_id,
                tracking_id=database_tracking_id,
                event_type=EventType(crossing.event_type.value),
                line_id=crossing.line_id,
                centroid={"x": crossing.centroid[0], "y": crossing.centroid[1]},
                occurred_at=crossing.occurred_at,
                event_metadata={
                    "byte_track_id": track.tracking_id,
                    "person_id": str(person_id) if person_id else None,
                    "confidence": track.confidence,
                    "direction": track.direction,
                    "snapshot_error": snapshot_error,
                    "presence_match": presence_match,
                    "matched_presence_person_id": (
                        str(open_presence.person_id)
                        if open_presence is not None and open_presence.person_id is not None
                        else None
                    ),
                },
            )
            session.add(event)
            await session.flush()
            await self._apply_presence_event(
                session,
                event=event,
                database_tracking_id=database_tracking_id,
                person_id=person_id,
                tracking=tracking,
                existing=open_presence,
            )
            legacy_snapshot: Snapshot | None = None
            if snapshot is not None:
                legacy_snapshot = Snapshot(
                    id=snapshot.snapshot_id,
                    event_id=event.id,
                    image_path=str(snapshot.image_path),
                    metadata_path=str(snapshot.metadata_path),
                    bbox={
                        "x1": track.bbox[0],
                        "y1": track.bbox[1],
                        "x2": track.bbox[2],
                        "y2": track.bbox[3],
                    },
                    saved_at=crossing.occurred_at,
                )
                session.add(legacy_snapshot)

            virtual_line = await session.scalar(
                select(VirtualLine).where(
                    VirtualLine.camera_id == tracking.camera_id,
                    VirtualLine.line_key == crossing.line_id,
                    VirtualLine.enabled.is_(True),
                )
            )
            zone_id = None
            if virtual_line is not None:
                zone_id = (
                    virtual_line.to_zone_id
                    if crossing_type == EventType.ENTER
                    else virtual_line.from_zone_id
                )
            if zone_id is None:
                mapping = await session.scalar(
                    select(CameraZoneMapping)
                    .where(
                        CameraZoneMapping.camera_id == tracking.camera_id,
                        CameraZoneMapping.enabled.is_(True),
                    )
                    .order_by(
                        CameraZoneMapping.is_primary.desc(),
                        CameraZoneMapping.created_at,
                    )
                )
                zone_id = mapping.zone_id if mapping is not None else None

            retention_days = self._evidence_retention_days
            processing_priority = ProcessingPriority.NORMAL
            if zone_id is not None:
                zone = await session.get(Zone, zone_id)
                if zone is not None:
                    retention_days = int(zone.retention_days)
                    processing_priority = zone.processing_priority

            capture_event = CaptureEvent(
                id=snapshot.capture_event_id if snapshot and snapshot.capture_event_id else event.id,
                idempotency_key=(
                    snapshot.idempotency_key
                    if snapshot and snapshot.idempotency_key
                    else f"crossing:{event.id}"
                ),
                source_event_id=event.id,
                camera_id=tracking.camera_id,
                zone_id=zone_id,
                virtual_line_id=virtual_line.id if virtual_line is not None else None,
                tracking_id=database_tracking_id,
                status=(
                    CaptureEventStatus.QUEUED
                    if snapshot is not None
                    else CaptureEventStatus.FAILED
                ),
                direction=track.direction,
                bbox={
                    "x1": track.bbox[0],
                    "y1": track.bbox[1],
                    "x2": track.bbox[2],
                    "y2": track.bbox[3],
                },
                centroid={
                    "x": crossing.centroid[0],
                    "y": crossing.centroid[1],
                },
                capture_quality={
                    "detector_confidence": track.confidence,
                    "bbox_width": max(0.0, track.bbox[2] - track.bbox[0]),
                    "bbox_height": max(0.0, track.bbox[3] - track.bbox[1]),
                },
                capture_metadata={
                    "event_type": crossing_type.value,
                    "line_id": crossing.line_id,
                    "byte_track_id": track.tracking_id,
                    "person_id": str(person_id) if person_id else None,
                },
                captured_at=crossing.occurred_at,
                failed_at=crossing.occurred_at if snapshot is None else None,
                error_message=snapshot_error if snapshot is None else None,
                attempt_count=0,
                retry_count=0,
                failure_reason=snapshot_error if snapshot is None else None,
                created_at=crossing.occurred_at,
                updated_at=crossing.occurred_at,
            )
            session.add(capture_event)

            if snapshot is not None:
                for asset in snapshot.assets:
                    session.add(
                        EvidenceAsset(
                            id=asset.asset_id,
                            capture_event_id=capture_event.id,
                            legacy_snapshot_id=(
                                legacy_snapshot.id
                                if asset.asset_type
                                == EvidenceAssetType.ANNOTATED_SNAPSHOT
                                else None
                            ),
                            asset_type=asset.asset_type,
                            sequence_index=asset.sequence_index,
                            storage_key=asset.storage_key,
                            checksum_sha256=asset.checksum_sha256,
                            integrity_status=EvidenceIntegrityStatus.VERIFIED,
                            mime_type=asset.mime_type,
                            size_bytes=asset.size_bytes,
                            width=asset.width,
                            height=asset.height,
                            is_primary=asset.is_primary,
                            asset_metadata=asset.metadata,
                            captured_at=crossing.occurred_at,
                            retention_until=(
                                crossing.occurred_at
                                + timedelta(days=retention_days)
                            ),
                        )
                    )
                processing_job = AIProcessingJob(
                    id=uuid4(),
                    capture_event_id=capture_event.id,
                    job_type=AIJobType.CAPTURE_INGESTION,
                    status=AIJobStatus.QUEUED,
                    priority=processing_priority,
                    idempotency_key=f"capture-ingestion:{capture_event.id}",
                    payload={
                        "capture_event_id": str(capture_event.id),
                        "camera_id": str(tracking.camera_id),
                        "zone_id": str(zone_id) if zone_id else None,
                    },
                    attempt_count=0,
                    max_attempts=self._ai_job_max_attempts,
                    available_at=crossing.occurred_at,
                    created_at=crossing.occurred_at,
                    updated_at=crossing.occurred_at,
                )
                session.add(processing_job)
            else:
                processing_job = None
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, {"reason": "integrity_conflict", "discard_snapshot": False}
            return True, {
                "id": str(event.id),
                "tracking_id": str(database_tracking_id),
                "byte_track_id": track.tracking_id,
                "person_id": str(person_id) if person_id else None,
                "event_type": event.event_type.value,
                "line_id": event.line_id,
                "centroid": event.centroid,
                "occurred_at": event.occurred_at.isoformat(),
                "snapshot_id": str(snapshot.snapshot_id) if snapshot else None,
                "capture_event_id": str(capture_event.id),
                "capture_status": capture_event.status.value,
                "processing_job_id": (
                    str(processing_job.id)
                    if processing_job is not None
                    else None
                ),
            }

    @staticmethod
    async def _find_open_presence(
        session: Any,
        *,
        person_id: UUID | None,
        database_tracking_id: UUID,
    ) -> PresenceSession | None:
        match_filter = (
            PresenceSession.person_id == person_id
            if person_id is not None
            else PresenceSession.entry_tracking_id == database_tracking_id
        )
        return await session.scalar(
            select(PresenceSession)
            .where(
                match_filter,
                PresenceSession.status.in_((PresenceStatus.ACTIVE, PresenceStatus.UNCERTAIN)),
            )
            .order_by(PresenceSession.entered_at.desc())
            .with_for_update()
        )

    @staticmethod
    def _logger_for_transition(
        message: str,
        *,
        crossing: CrossingEvent,
        person_id: UUID | None,
    ) -> None:
        logging.getLogger(__name__).info(
            "%s event=%s tracking_id=%s person_id=%s",
            message,
            crossing.event_type.value,
            crossing.tracking_id,
            person_id,
        )

    async def current_occupancy(self) -> dict[str, int]:
        """Return camera-confirmed occupancy and report uncertain presence separately."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(PresenceSession.status, func.count())
                    .where(PresenceSession.status.in_((PresenceStatus.ACTIVE, PresenceStatus.UNCERTAIN)))
                    .group_by(PresenceSession.status)
                )
            ).all()
            counts = {status: int(count) for status, count in rows}
            confirmed = counts.get(PresenceStatus.ACTIVE, 0)
            uncertain = counts.get(PresenceStatus.UNCERTAIN, 0)
            return {
                "confirmed": confirmed,
                "uncertain": uncertain,
                "total": confirmed,
            }

    async def mark_camera_presence_uncertain(
        self, camera_id: UUID, *, occurred_at: datetime | None = None
    ) -> dict[str, int]:
        """Remove camera-lost presence from current occupancy and flag it separately."""
        timestamp = occurred_at or datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                update(PresenceSession)
                .where(
                    PresenceSession.camera_id == camera_id,
                    PresenceSession.status == PresenceStatus.ACTIVE,
                )
                .values(
                    status=PresenceStatus.UNCERTAIN,
                    uncertain_since=timestamp,
                    updated_at=timestamp,
                )
            )
            await session.commit()
        return await self.current_occupancy()

    async def confirm_person_presence(
        self,
        person_id: UUID | None,
        *,
        camera_id: UUID,
        confirmed_at: datetime,
    ) -> None:
        """Restore an uncertain session when ReID observes the same person again."""
        if person_id is None:
            return
        async with self._session_factory() as session:
            await session.execute(
                update(PresenceSession)
                .where(
                    PresenceSession.person_id == person_id,
                    PresenceSession.status == PresenceStatus.UNCERTAIN,
                )
                .values(
                    status=PresenceStatus.ACTIVE,
                    camera_id=camera_id,
                    uncertain_since=None,
                    last_confirmed_at=confirmed_at,
                    updated_at=confirmed_at,
                )
            )
            await session.commit()

    @staticmethod
    async def _apply_presence_event(
        session: Any,
        *,
        event: Event,
        database_tracking_id: UUID,
        person_id: UUID | None,
        tracking: Tracking,
        existing: PresenceSession | None,
    ) -> None:
        if event.event_type == EventType.ENTER:
            assert existing is None
            session.add(
                PresenceSession(
                    id=uuid4(),
                    person_id=person_id,
                    camera_id=tracking.camera_id,
                    entry_tracking_id=database_tracking_id,
                    entry_event_id=event.id,
                    status=PresenceStatus.ACTIVE,
                    entered_at=event.occurred_at,
                    last_confirmed_at=event.occurred_at,
                    created_at=event.occurred_at,
                    updated_at=event.occurred_at,
                )
            )
            return

        assert existing is not None
        existing.status = PresenceStatus.CLOSED
        existing.exit_tracking_id = database_tracking_id
        existing.exit_event_id = event.id
        existing.exited_at = event.occurred_at
        existing.uncertain_since = None
        existing.last_confirmed_at = event.occurred_at
        existing.updated_at = event.occurred_at

    @staticmethod
    def remove_snapshot(snapshot: SnapshotResult | None) -> None:
        if snapshot is None:
            return
        paths = {snapshot.image_path, snapshot.metadata_path}
        paths.update(asset.path for asset in snapshot.assets)
        for path in paths:
            Path(path).unlink(missing_ok=True)
