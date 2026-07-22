"""ByteTrack wrapper that adds track history and human-readable direction."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.detector import Detection


@dataclass(frozen=True, slots=True)
class TrackedDetection:
    """A YOLO detection associated with one ByteTrack identity."""

    tracking_id: int
    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
    centroid: tuple[float, float]
    direction: str
    history: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class _TrackerInput:
    """Minimal Ultralytics Results-like detection collection."""

    xyxy: Any
    xywh: Any
    conf: Any
    cls: Any

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, index: Any) -> "_TrackerInput":
        return _TrackerInput(
            xyxy=self.xyxy[index],
            xywh=self.xywh[index],
            conf=self.conf[index],
            cls=self.cls[index],
        )


TrackerFactory = Callable[[Any, int], Any]
ArrayFactory = Callable[[list[Any]], Any]


class TrackingService:
    """Associate consecutive YOLO detections using Ultralytics ByteTrack.

    ByteTrack combines motion prediction with two-stage confidence matching. This
    makes IDs substantially more stable around short occlusions and people
    passing one another; long visual ambiguities are handled later by ReID.
    """

    def __init__(
        self,
        settings: Any | None = None,
        *,
        tracker_factory: TrackerFactory | None = None,
        array_factory: ArrayFactory | None = None,
    ) -> None:
        self._settings = settings or self._load_settings()
        self._tracker_factory = tracker_factory or self._bytetrack_factory
        self._array_factory = array_factory or self._numpy_array
        self._tracker: Any | None = None
        self._histories: dict[int, deque[tuple[float, float]]] = {}
        self._last_seen_frame: dict[int, int] = {}
        self._frame_number = 0
        self._logger = logging.getLogger(__name__)

    def update(self, detections: Sequence[Detection]) -> list[TrackedDetection]:
        """Update ByteTrack with YOLO detections from one video frame."""
        self._frame_number += 1
        tracker = self._get_tracker()
        tracker_input = self._to_tracker_input(detections)
        tracks = tracker.update(tracker_input)
        tracked = self._to_tracked_detections(tracks, detections)
        self._remove_inactive_histories()
        return tracked

    def reset(self) -> None:
        """Discard tracker state and all centroid history, e.g. after camera restart."""
        self._tracker = None
        self._histories.clear()
        self._last_seen_frame.clear()
        self._frame_number = 0
        self._logger.info("ByteTrack state reset")

    def _get_tracker(self) -> Any:
        if self._tracker is None:
            self._tracker = self._tracker_factory(
                self._tracker_arguments(), self._settings.bytetrack_frame_rate
            )
            self._logger.info("ByteTrack initialized")
        return self._tracker

    def _tracker_arguments(self) -> SimpleNamespace:
        return SimpleNamespace(
            track_high_thresh=self._settings.bytetrack_track_high_threshold,
            track_low_thresh=self._settings.bytetrack_track_low_threshold,
            new_track_thresh=self._settings.bytetrack_new_track_threshold,
            track_buffer=self._settings.bytetrack_track_buffer,
            match_thresh=self._settings.bytetrack_match_threshold,
            fuse_score=True,
        )

    def _to_tracker_input(self, detections: Sequence[Detection]) -> _TrackerInput:
        boxes = [list(detection.bbox) for detection in detections]
        xywh = [
            [
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                x2 - x1,
                y2 - y1,
            ]
            for x1, y1, x2, y2 in (detection.bbox for detection in detections)
        ]
        return _TrackerInput(
            xyxy=self._array_factory(boxes),
            xywh=self._array_factory(xywh),
            conf=self._array_factory([detection.confidence for detection in detections]),
            cls=self._array_factory([detection.class_id for detection in detections]),
        )

    def _to_tracked_detections(
        self, tracks: Any, detections: Sequence[Detection]
    ) -> list[TrackedDetection]:
        results: list[TrackedDetection] = []
        for track in tracks:
            original_index = int(track[-1])
            if original_index < 0 or original_index >= len(detections):
                self._logger.warning("ByteTrack returned an invalid detection index: %s", original_index)
                continue
            detection = detections[original_index]
            tracking_id = int(track[4])
            history = self._histories.setdefault(
                tracking_id, deque(maxlen=self._settings.bytetrack_history_size)
            )
            previous_centroid = history[-1] if history else None
            history.append(detection.centroid)
            self._last_seen_frame[tracking_id] = self._frame_number
            results.append(
                TrackedDetection(
                    tracking_id=tracking_id,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    class_id=detection.class_id,
                    class_name=detection.class_name,
                    centroid=detection.centroid,
                    direction=self._direction(previous_centroid, detection.centroid),
                    history=tuple(history),
                )
            )
        return results

    def _direction(
        self, previous: tuple[float, float] | None, current: tuple[float, float]
    ) -> str:
        if previous is None:
            return "unknown"
        delta_x = current[0] - previous[0]
        delta_y = current[1] - previous[1]
        minimum = self._settings.bytetrack_direction_min_pixels
        if abs(delta_x) < minimum and abs(delta_y) < minimum:
            return "stationary"
        if abs(delta_x) >= abs(delta_y):
            return "right" if delta_x > 0 else "left"
        return "down" if delta_y > 0 else "up"

    def _remove_inactive_histories(self) -> None:
        threshold = self._frame_number - self._settings.bytetrack_max_inactive_frames
        inactive_ids = [track_id for track_id, seen in self._last_seen_frame.items() if seen < threshold]
        for track_id in inactive_ids:
            self._last_seen_frame.pop(track_id, None)
            self._histories.pop(track_id, None)

    @staticmethod
    def _bytetrack_factory(arguments: Any, frame_rate: int) -> Any:
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
        except ImportError as error:
            raise RuntimeError("Install Ultralytics to use ByteTrack") from error
        return TrackingService._instantiate_bytetracker(
            BYTETracker, arguments, frame_rate
        )

    @staticmethod
    def _instantiate_bytetracker(
        tracker_type: type[Any], arguments: Any, frame_rate: int
    ) -> Any:
        """Support Ultralytics releases with and without ``frame_rate``."""
        import inspect

        parameters = inspect.signature(tracker_type).parameters
        if "frame_rate" in parameters:
            return tracker_type(arguments, frame_rate=frame_rate)
        return tracker_type(arguments)

    @staticmethod
    def _numpy_array(values: list[Any]) -> Any:
        try:
            import numpy as np
        except ImportError as error:
            raise RuntimeError("Install NumPy to use ByteTrack") from error
        return np.asarray(values, dtype=np.float32)

    @staticmethod
    def _load_settings() -> Any:
        from app.config.settings import get_settings

        return get_settings()
