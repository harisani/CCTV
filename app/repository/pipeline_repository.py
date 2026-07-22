"""Short-lived transactional persistence boundary for realtime workers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import Event, EventType, Snapshot, Tracking
from app.repository.person_repository import PersonRepository
if TYPE_CHECKING:
    from app.services.crossing_service import CrossingEvent
    from app.storage import SnapshotResult
    from app.tracker import TrackedDetection


class PipelineRepository:
    """Keep camera loops independent from long-lived SQLAlchemy sessions."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

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
                return False, {}
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
                },
            )
            session.add(event)
            if snapshot is not None:
                session.add(
                    Snapshot(
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
                )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, {}
            return True, {
                "id": str(event.id),
                "tracking_id": str(database_tracking_id),
                "byte_track_id": track.tracking_id,
                "person_id": str(person_id) if person_id else None,
                "event_type": event.event_type.value,
                "line_id": event.line_id,
                "centroid": event.centroid,
                "occurred_at": event.occurred_at.isoformat(),
                "snapshot_path": str(snapshot.image_path) if snapshot else None,
            }

    async def current_occupancy(self) -> int:
        from sqlalchemy import func

        async with self._session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(Tracking)
                    .where(Tracking.is_active.is_(True))
                )
                or 0
            )

    @staticmethod
    def remove_snapshot(snapshot: SnapshotResult | None) -> None:
        if snapshot is None:
            return
        Path(snapshot.image_path).unlink(missing_ok=True)
        Path(snapshot.metadata_path).unlink(missing_ok=True)
