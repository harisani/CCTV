"""End-to-end per-camera realtime AI orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.detector import DetectorService
from app.reid import PersonReIdentificationService
from app.repository import PipelineRepository
from app.services.crossing_service import (
    CrossingEvent,
    CrossingService,
    MultiLineCrossingService,
    VirtualLineConfig,
)
from app.storage import SnapshotResult, SnapshotService
from app.tracker import TrackedDetection, TrackingService


@dataclass(frozen=True, slots=True)
class PipelineFrame:
    processed: bool
    tracks: list[dict[str, Any]]
    events: list[dict[str, Any]]
    occupancy: dict[str, int] | None = None


@dataclass(slots=True)
class _PendingEvent:
    database_tracking_id: UUID
    person_id: UUID | None
    crossing: CrossingEvent
    track: TrackedDetection
    snapshot: SnapshotResult | None
    snapshot_error: str | None


class CameraRealtimePipeline:
    """Own stateful tracking/crossing state for exactly one camera."""

    def __init__(
        self,
        *,
        camera_id: UUID,
        settings: Any,
        detector: DetectorService,
        tracker: TrackingService,
        reidentification: PersonReIdentificationService,
        crossing: CrossingService | MultiLineCrossingService,
        snapshots: SnapshotService,
        persistence: PipelineRepository,
        inference_semaphore: asyncio.Semaphore,
    ) -> None:
        self.camera_id = camera_id
        self._settings = settings
        self._detector = detector
        self._tracker = tracker
        self._reidentification = reidentification
        self._crossing = crossing
        self._snapshots = snapshots
        self._persistence = persistence
        self._inference_semaphore = inference_semaphore
        self._database_tracks: dict[int, UUID] = {}
        self._person_ids: dict[int, UUID | None] = {}
        self._embedding_ids: dict[int, UUID] = {}
        self._last_seen_frame: dict[int, int] = {}
        self._last_dashboard_tracks: list[dict[str, Any]] = []
        self._pending_events: list[_PendingEvent] = []
        self._frame_number = 0
        self._last_processed_at = 0.0
        self._last_persisted_at = 0.0
        self._logger = logging.getLogger(f"{__name__}.{camera_id}")

    async def start(self) -> None:
        """Recover safely: stale tracks close while open presence becomes uncertain."""
        await self._persistence.mark_camera_presence_uncertain(
            self.camera_id,
            occurred_at=datetime.now(UTC),
        )
        await self._persistence.close_camera_trackings(self.camera_id)

    async def stop(self) -> None:
        await self._flush_pending_events()
        await self._persistence.close_trackings(list(self._database_tracks.values()))
        self._tracker.reset()
        self._crossing.reset()
        self._database_tracks.clear()
        self._person_ids.clear()
        self._embedding_ids.clear()
        self._last_seen_frame.clear()

    async def mark_camera_uncertain(self, occurred_at: datetime | None = None) -> dict[str, int]:
        """Move camera-lost sessions out of current occupancy into uncertain presence."""
        return await self._persistence.mark_camera_presence_uncertain(
            self.camera_id,
            occurred_at=occurred_at or datetime.now(UTC),
        )

    def configure_crossing(
        self,
        config: list[dict[str, Any]] | dict[str, Any] | None,
    ) -> None:
        """Replace crossing geometry while preserving detector and model instances."""
        if config is None:
            crossing = CrossingService(settings=self._settings)
        else:
            mappings = config if isinstance(config, list) else [config]
            crossing = MultiLineCrossingService(
                [
                    VirtualLineConfig.from_mapping(
                        mapping,
                        max_inactive_frames=(
                            self._settings.crossing_max_inactive_frames
                        ),
                        hysteresis_ratio=(
                            self._settings.crossing_hysteresis_ratio
                        ),
                        event_cooldown_frames=(
                            self._settings.crossing_event_cooldown_frames
                        ),
                    )
                    for mapping in mappings
                ]
            )
        self._crossing.reset()
        self._crossing = crossing
        configs = (
            crossing.configs
            if isinstance(crossing, MultiLineCrossingService)
            else (crossing.config,)
        )
        self._logger.info(
            "Crossing configuration applied lines=%s enabled=%s",
            ",".join(item.line_id for item in configs) or "none",
            sum(item.enabled for item in configs),
        )

    async def process(
        self, frame: Any, *, captured_at: datetime | None = None
    ) -> PipelineFrame:
        now = time.monotonic()
        interval = 1 / self._settings.ai_pipeline_fps
        if now - self._last_processed_at < interval:
            return PipelineFrame(False, self._last_dashboard_tracks, [])
        self._last_processed_at = now
        self._frame_number += 1
        captured_at = captured_at or datetime.now(UTC)

        retried_events = await self._flush_pending_events()
        async with self._inference_semaphore:
            detections = await asyncio.to_thread(self._detector.predict, frame)
        people = [
            detection
            for detection in detections
            if detection.class_id == self._settings.ai_person_class_id
        ]
        tracks = await asyncio.to_thread(self._tracker.update, people)
        await self._register_new_tracks(frame, tracks, captured_at)
        await self._persist_centroids_if_due(tracks, now, captured_at)
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2:
            self._crossing.set_frame_size(int(shape[1]), int(shape[0]))
        events = self._crossing.process(tracks, occurred_at=captured_at)
        published_events = retried_events + await self._handle_crossings(
            frame, tracks, events
        )
        await self._expire_inactive_tracks(tracks, captured_at)
        self._last_dashboard_tracks = [self._dashboard_track(track) for track in tracks]
        occupancy = (
            await self._persistence.current_occupancy() if published_events else None
        )
        return PipelineFrame(
            True,
            self._last_dashboard_tracks,
            published_events,
            occupancy,
        )

    async def _register_new_tracks(
        self,
        frame: Any,
        tracks: list[TrackedDetection],
        captured_at: datetime,
    ) -> None:
        for track in tracks:
            self._last_seen_frame[track.tracking_id] = self._frame_number
            if track.tracking_id in self._database_tracks:
                continue
            person_id = await self._identify_once(frame, track, captured_at)
            try:
                database_id = await self._persistence.start_tracking(
                    camera_id=self.camera_id,
                    byte_track_id=track.tracking_id,
                    person_id=person_id,
                    centroid=track.centroid,
                    bbox=track.bbox,
                    detector_confidence=track.confidence,
                    direction=track.direction,
                    detector_model=str(
                        getattr(self._settings, "yolo_model_path", "unknown")
                    ),
                    started_at=captured_at,
                )
            except Exception:
                self._logger.exception(
                    "Unable to persist new tracking byte_track_id=%s",
                    track.tracking_id,
                )
                continue
            self._database_tracks[track.tracking_id] = database_id
            try:
                await self._persistence.confirm_person_presence(
                    person_id,
                    camera_id=self.camera_id,
                    confirmed_at=captured_at,
                )
            except Exception:
                self._logger.exception(
                    "Unable to confirm presence byte_track_id=%s",
                    track.tracking_id,
                )
            embedding_id = self._embedding_ids.get(track.tracking_id)
            if embedding_id is not None:
                try:
                    await self._persistence.link_embedding(embedding_id, database_id)
                except Exception:
                    self._logger.exception(
                        "Unable to link ReID template to tracking byte_track_id=%s",
                        track.tracking_id,
                    )

    async def _identify_once(
        self, frame: Any, track: TrackedDetection, captured_at: datetime
    ) -> UUID | None:
        if not getattr(self._settings, "enable_realtime_reid", False):
            return None
        if track.tracking_id in self._person_ids:
            return self._person_ids[track.tracking_id]
        x1, y1, x2, y2 = track.bbox
        if (
            x2 - x1 < self._settings.reid_min_crop_width
            or y2 - y1 < self._settings.reid_min_crop_height
        ):
            self._person_ids[track.tracking_id] = None
            return None
        try:
            crop = self._reidentification.crop_person(frame, track.bbox)
            quality = self._reidentification.quality_score(
                crop, detector_confidence=track.confidence
            )
            if quality < self._settings.reid_min_quality_score:
                self._logger.info(
                    "ReID skipped low-quality crop byte_track_id=%s quality=%.3f",
                    track.tracking_id,
                    quality,
                )
                self._person_ids[track.tracking_id] = None
                return None
            async with self._inference_semaphore:
                embedding = await asyncio.to_thread(
                    self._reidentification.extract_embedding, crop
                )
            result = await self._persistence.identify_person(
                self._reidentification,
                embedding,
                quality_score=quality,
                camera_id=self.camera_id,
                captured_at=captured_at,
            )
            person_id = result.person_id
            if result.embedding_id is not None:
                self._embedding_ids[track.tracking_id] = result.embedding_id
        except Exception:
            self._logger.exception(
                "ReID failed byte_track_id=%s; tracking continues without person_id",
                track.tracking_id,
            )
            person_id = None
        self._person_ids[track.tracking_id] = person_id
        return person_id

    async def _persist_centroids_if_due(
        self,
        tracks: list[TrackedDetection],
        now: float,
        captured_at: datetime,
    ) -> None:
        if (
            now - self._last_persisted_at
            < self._settings.ai_tracking_persist_interval_seconds
        ):
            return
        updates = [
            (self._database_tracks[track.tracking_id], track)
            for track in tracks
            if track.tracking_id in self._database_tracks
        ]
        try:
            await self._persistence.update_trackings(
                updates,
                observed_at=captured_at,
            )
            self._last_persisted_at = now
        except Exception:
            self._logger.exception("Unable to persist tracking centroids")

    async def _handle_crossings(
        self,
        frame: Any,
        tracks: list[TrackedDetection],
        crossings: list[CrossingEvent],
    ) -> list[dict[str, Any]]:
        by_id = {track.tracking_id: track for track in tracks}
        published: list[dict[str, Any]] = []
        for crossing in crossings:
            track = by_id.get(crossing.tracking_id)
            database_id = self._database_tracks.get(crossing.tracking_id)
            if track is None or database_id is None:
                self._logger.error(
                    "Crossing cannot be persisted without tracking row byte_track_id=%s",
                    crossing.tracking_id,
                )
                continue
            snapshot: SnapshotResult | None = None
            snapshot_error: str | None = None
            try:
                snapshot = await self._snapshots.save_async(
                    frame,
                    crossing,
                    track,
                    camera_id=str(self.camera_id),
                )
            except Exception as error:
                snapshot_error = str(error)[:500]
                self._logger.exception(
                    "Snapshot failed for crossing event_id=%s", crossing.event_id
                )
            pending = _PendingEvent(
                database_id,
                self._person_ids.get(track.tracking_id),
                crossing,
                track,
                snapshot,
                snapshot_error,
            )
            payload = await self._persist_pending(pending)
            if payload is not None:
                published.append(payload)
        return published

    async def _persist_pending(
        self, pending: _PendingEvent
    ) -> dict[str, Any] | None:
        try:
            created, payload = await self._persistence.persist_crossing(
                database_tracking_id=pending.database_tracking_id,
                person_id=pending.person_id,
                crossing=pending.crossing,
                track=pending.track,
                snapshot=pending.snapshot,
                snapshot_error=pending.snapshot_error,
            )
        except Exception:
            self._logger.exception(
                "Event persistence failed; queued event_id=%s",
                pending.crossing.event_id,
            )
            if len(self._pending_events) < self._settings.ai_event_retry_queue_size:
                self._pending_events.append(pending)
            else:
                self._logger.critical("Event retry queue is full; preserving snapshot files")
            return None
        if not created:
            if payload.get("discard_snapshot"):
                self._persistence.remove_snapshot(pending.snapshot)
                self._logger.info(
                    "Rejected crossing discarded event_id=%s reason=%s",
                    pending.crossing.event_id,
                    payload.get("reason"),
                )
            else:
                self._logger.info(
                    "Event not created event_id=%s reason=%s; retaining snapshot for safety",
                    pending.crossing.event_id,
                    payload.get("reason"),
                )
            return None
        return payload

    async def _flush_pending_events(self) -> list[dict[str, Any]]:
        if not self._pending_events:
            return []
        pending, self._pending_events = self._pending_events, []
        published: list[dict[str, Any]] = []
        for item in pending:
            payload = await self._persist_pending(item)
            if payload is not None:
                published.append(payload)
        return published

    async def _expire_inactive_tracks(
        self, tracks: list[TrackedDetection], ended_at: datetime
    ) -> None:
        active = {track.tracking_id for track in tracks}
        threshold = self._frame_number - self._settings.ai_track_inactive_frames
        expired = [
            track_id
            for track_id, last_seen in self._last_seen_frame.items()
            if track_id not in active and last_seen < threshold
        ]
        database_ids = [
            self._database_tracks[track_id]
            for track_id in expired
            if track_id in self._database_tracks
        ]
        if database_ids:
            try:
                await self._persistence.close_trackings(
                    database_ids, ended_at=ended_at
                )
            except Exception:
                self._logger.exception("Unable to close inactive tracking rows")
                return
        for track_id in expired:
            self._last_seen_frame.pop(track_id, None)
            self._database_tracks.pop(track_id, None)
            self._person_ids.pop(track_id, None)
            self._embedding_ids.pop(track_id, None)

    def _dashboard_track(self, track: TrackedDetection) -> dict[str, Any]:
        person_id = self._person_ids.get(track.tracking_id)
        return {
            "tracking_id": track.tracking_id,
            "person_id": str(person_id) if person_id else None,
            "bbox": list(track.bbox),
            "confidence": track.confidence,
            "centroid": list(track.centroid),
            "direction": track.direction,
        }

class RealtimePipelineFactory:
    """Share model weights while producing isolated stateful camera pipelines."""

    def __init__(self, settings: Any, session_factory: Any) -> None:
        self._settings = settings
        self._detector = DetectorService(settings)
        self._reidentification = PersonReIdentificationService(settings)
        self._snapshots = SnapshotService(settings)
        self._persistence = PipelineRepository(
            session_factory,
            evidence_retention_days=settings.evidence_default_retention_days,
            ai_job_max_attempts=settings.ai_job_max_attempts,
        )
        self._inference_semaphore = asyncio.Semaphore(
            settings.ai_max_concurrent_inferences
        )

    def create(self, camera_id: UUID) -> CameraRealtimePipeline:
        return CameraRealtimePipeline(
            camera_id=camera_id,
            settings=self._settings,
            detector=self._detector,
            tracker=TrackingService(self._settings),
            reidentification=self._reidentification,
            crossing=CrossingService(settings=self._settings),
            snapshots=self._snapshots,
            persistence=self._persistence,
            inference_semaphore=self._inference_semaphore,
        )
