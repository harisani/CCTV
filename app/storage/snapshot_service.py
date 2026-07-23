"""File-system snapshot storage for line-crossing events."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.services.crossing_service import CrossingEvent
from app.tracker import TrackedDetection


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """Locations and identity of one saved event snapshot."""

    snapshot_id: UUID
    image_path: Path
    metadata_path: Path


class SnapshotService:
    """Persist annotated JPEG snapshots and JSON metadata below ``storage/YYYY/MM/DD``."""

    def __init__(self, settings: Any | None = None, *, cv2_module: Any | None = None) -> None:
        self._settings = settings or self._load_settings()
        self._cv2_module = cv2_module
        self._storage_root = Path(self._settings.storage_path)
        self._logger = logging.getLogger(__name__)

    def save(
        self,
        frame: Any,
        event: CrossingEvent,
        tracked_person: TrackedDetection,
        *,
        camera_id: str,
    ) -> SnapshotResult:
        """Save one annotated event frame and its sidecar metadata JSON file."""
        if not camera_id.strip():
            raise ValueError("camera_id must not be empty")
        captured_at = event.occurred_at.astimezone(UTC)
        destination = self._event_directory(captured_at)
        destination.mkdir(parents=True, exist_ok=True)

        snapshot_id = uuid4()
        filename = f"{captured_at:%Y%m%d_%H%M%S}_{snapshot_id}.jpg"
        image_path = destination / filename
        metadata_path = image_path.with_suffix(".json")

        annotated_frame = self._draw_person(frame, tracked_person, event)
        cv2 = self._get_cv2()
        success = cv2.imwrite(
            str(image_path),
            annotated_frame,
            [cv2.IMWRITE_JPEG_QUALITY, self._settings.snapshot_jpeg_quality],
        )
        if not success:
            raise OSError(f"Failed to write snapshot image: {image_path}")

        metadata = {
            "snapshot_id": str(snapshot_id),
            "camera_id": camera_id,
            "occurred_at": captured_at.isoformat(),
            "event": {
                "event_id": str(event.event_id),
                "event_type": event.event_type.value,
                "line_id": event.line_id,
                "tracking_id": event.tracking_id,
                "centroid": list(event.centroid),
            },
            "person": {
                "tracking_id": tracked_person.tracking_id,
                "bbox": list(tracked_person.bbox),
                "confidence": tracked_person.confidence,
                "class_id": tracked_person.class_id,
                "class_name": tracked_person.class_name,
                "centroid": list(tracked_person.centroid),
                "direction": tracked_person.direction,
            },
            "image_path": str(image_path),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self._logger.info("Snapshot saved for %s: %s", event.event_type, image_path)
        return SnapshotResult(snapshot_id, image_path, metadata_path)

    async def save_async(
        self,
        frame: Any,
        event: CrossingEvent,
        tracked_person: TrackedDetection,
        *,
        camera_id: str,
    ) -> SnapshotResult:
        """Save a snapshot without blocking an async video-processing coordinator."""
        return await asyncio.to_thread(
            self.save, frame, event, tracked_person, camera_id=camera_id
        )

    def _event_directory(self, occurred_at: datetime) -> Path:
        return self._storage_root / f"{occurred_at:%Y}" / f"{occurred_at:%m}" / f"{occurred_at:%d}"

    def _draw_person(self, frame: Any, person: TrackedDetection, event: CrossingEvent) -> Any:
        cv2 = self._get_cv2()
        annotated = frame.copy()
        x1, y1, x2, y2 = (round(value) for value in person.bbox)
        color = (0, 255, 0) if event.event_type.value == "ENTER" else (0, 0, 255)
        label = f"{event.event_type.value} | ID {person.tracking_id}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )
        return annotated

    def _get_cv2(self) -> Any:
        if self._cv2_module is not None:
            return self._cv2_module
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("Install OpenCV to save snapshots") from error
        self._cv2_module = cv2
        return cv2

    @staticmethod
    def _load_settings() -> Any:
        from app.config.settings import get_settings

        return get_settings()
