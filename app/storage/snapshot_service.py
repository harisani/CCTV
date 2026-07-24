"""File-system snapshot storage for line-crossing events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.models import EvidenceAssetType
from app.services.crossing_service import CrossingEvent
from app.storage.evidence_storage_service import EvidenceFile, EvidenceStorageService
from app.tracker import TrackedDetection


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """Locations and identity of one saved event snapshot."""

    snapshot_id: UUID
    image_path: Path
    metadata_path: Path
    capture_event_id: UUID | None = None
    idempotency_key: str | None = None
    assets: tuple[EvidenceFile, ...] = ()


class SnapshotService:
    """Persist annotated JPEG snapshots and JSON metadata below ``storage/YYYY/MM/DD``."""

    def __init__(self, settings: Any | None = None, *, cv2_module: Any | None = None) -> None:
        self._settings = settings or self._load_settings()
        self._cv2_module = cv2_module
        self._storage_root = Path(self._settings.storage_path)
        self._evidence = EvidenceStorageService(
            self._settings, cv2_module=cv2_module
        )
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
        snapshot_id = uuid4()
        filename = f"{captured_at:%Y%m%d_%H%M%S}_{snapshot_id}.jpg"
        prefix = (
            f"{captured_at:%Y}/{captured_at:%m}/{captured_at:%d}/"
            f"{Path(filename).stem}"
        )
        written: list[EvidenceFile] = []
        try:
            written.append(
                self._evidence.write_image(
                    f"{prefix}_original.jpg",
                    frame,
                    asset_type=EvidenceAssetType.ORIGINAL_SNAPSHOT,
                    metadata={"camera_id": camera_id},
                )
            )
            annotated = self._draw_person(frame, tracked_person, event)
            annotated_file = self._evidence.write_image(
                f"{prefix}.jpg",
                annotated,
                asset_type=EvidenceAssetType.ANNOTATED_SNAPSHOT,
                is_primary=True,
                metadata={
                    "event_type": event.event_type.value,
                    "tracking_id": tracked_person.tracking_id,
                },
            )
            written.append(annotated_file)

            body = self._crop_person(frame, tracked_person)
            if body is not None:
                written.append(
                    self._evidence.write_image(
                        f"{prefix}_body.jpg",
                        body,
                        asset_type=EvidenceAssetType.FULL_BODY,
                        metadata={"bbox": list(tracked_person.bbox)},
                    )
                )
                thumbnail = self._thumbnail(body)
                if thumbnail is not None:
                    written.append(
                        self._evidence.write_image(
                            f"{prefix}_thumb.jpg",
                            thumbnail,
                            asset_type=EvidenceAssetType.THUMBNAIL,
                        )
                    )

            metadata = {
                "schema_version": 2,
                "snapshot_id": str(snapshot_id),
                "capture_event_id": str(event.event_id),
                "idempotency_key": f"crossing:{event.event_id}",
                "camera_id": camera_id,
                "captured_at": captured_at.isoformat(),
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
                "assets": [
                    {
                        "asset_id": str(asset.asset_id),
                        "asset_type": asset.asset_type.value,
                        "storage_key": asset.storage_key,
                        "checksum_sha256": asset.checksum_sha256,
                        "size_bytes": asset.size_bytes,
                    }
                    for asset in written
                ],
            }
            metadata_file = self._evidence.write_json(
                f"{prefix}.json",
                metadata,
                metadata={"schema_version": 2},
            )
            written.append(metadata_file)
        except Exception:
            self._evidence.remove(written)
            raise

        self._logger.info(
            "Evidence bundle saved event_id=%s assets=%s",
            event.event_id,
            len(written),
        )
        return SnapshotResult(
            snapshot_id=snapshot_id,
            image_path=annotated_file.path,
            metadata_path=metadata_file.path,
            capture_event_id=event.event_id,
            idempotency_key=f"crossing:{event.event_id}",
            assets=tuple(written),
        )

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

    @staticmethod
    def _crop_person(frame: Any, person: TrackedDetection) -> Any | None:
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None
        height, width = int(shape[0]), int(shape[1])
        x1, y1, x2, y2 = (round(value) for value in person.bbox)
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        return crop.copy() if getattr(crop, "size", 0) else None

    def _thumbnail(self, image: Any) -> Any | None:
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2 or shape[1] <= 0:
            return None
        width = min(
            int(getattr(self._settings, "evidence_thumbnail_width", 320)),
            int(shape[1]),
        )
        height = max(1, round(int(shape[0]) * width / int(shape[1])))
        cv2 = self._get_cv2()
        if not hasattr(cv2, "resize"):
            return None
        return cv2.resize(image, (width, height))

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
