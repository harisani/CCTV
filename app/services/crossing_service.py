"""Virtual-line and polygon crossing event detection."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from app.tracker import TrackedDetection

LineType = Literal["horizontal", "vertical", "polygon"]
Direction = Literal["up", "down", "left", "right"]
Point = tuple[float, float]


class CrossingType(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


@dataclass(frozen=True, slots=True)
class VirtualLineConfig:
    """Geometry and entry convention of one virtual doorway boundary."""

    line_id: str
    line_type: LineType
    position: float | None = None
    enter_direction: Direction = "down"
    polygon_points: tuple[Point, ...] = ()
    max_inactive_frames: int = 300

    def __post_init__(self) -> None:
        if not self.line_id.strip():
            raise ValueError("line_id must not be empty")
        if self.line_type in ("horizontal", "vertical") and self.position is None:
            raise ValueError("position is required for a horizontal or vertical line")
        if self.line_type == "horizontal" and self.enter_direction not in ("up", "down"):
            raise ValueError("horizontal line enter_direction must be 'up' or 'down'")
        if self.line_type == "vertical" and self.enter_direction not in ("left", "right"):
            raise ValueError("vertical line enter_direction must be 'left' or 'right'")
        if self.line_type == "polygon" and len(self.polygon_points) < 3:
            raise ValueError("polygon requires at least three points")
        if self.max_inactive_frames <= 0:
            raise ValueError("max_inactive_frames must be greater than zero")

    @classmethod
    def from_settings(cls, settings: Any) -> "VirtualLineConfig":
        points = _parse_polygon_points(settings.crossing_polygon_points)
        return cls(
            line_id=settings.crossing_line_id,
            line_type=settings.crossing_line_type,
            position=settings.crossing_line_position,
            enter_direction=settings.crossing_enter_direction,
            polygon_points=points,
            max_inactive_frames=settings.crossing_max_inactive_frames,
        )


@dataclass(frozen=True, slots=True)
class CrossingEvent:
    """One de-duplicated movement over a configured virtual boundary."""

    event_id: UUID
    event_type: CrossingType
    line_id: str
    tracking_id: int
    centroid: Point
    occurred_at: datetime


class CrossingService:
    """Create ENTER/EXIT events from tracked people crossing one virtual line."""

    def __init__(self, config: VirtualLineConfig | None = None, *, settings: Any | None = None) -> None:
        if config is not None and settings is not None:
            raise ValueError("Pass either config or settings, not both")
        if config is None:
            config = VirtualLineConfig.from_settings(settings or self._load_settings())
        self._config = config
        self._last_positions: dict[int, Point] = {}
        self._last_seen_frame: dict[int, int] = {}
        self._emitted_events: set[tuple[int, CrossingType]] = set()
        self._frame_number = 0
        self._logger = logging.getLogger(__name__)

    def process(self, tracks: Sequence[TrackedDetection]) -> list[CrossingEvent]:
        """Evaluate current tracks and return only new crossing events."""
        self._frame_number += 1
        events: list[CrossingEvent] = []
        for track in tracks:
            previous = self._last_positions.get(track.tracking_id)
            if previous is not None:
                event_type = self._crossing_type(previous, track.centroid)
                if event_type is not None and (track.tracking_id, event_type) not in self._emitted_events:
                    event = CrossingEvent(
                        event_id=uuid4(),
                        event_type=event_type,
                        line_id=self._config.line_id,
                        tracking_id=track.tracking_id,
                        centroid=track.centroid,
                        occurred_at=datetime.now(UTC),
                    )
                    self._emitted_events.add((track.tracking_id, event_type))
                    events.append(event)
                    self._logger.info(
                        "Crossing event=%s line=%s tracking_id=%s",
                        event_type,
                        self._config.line_id,
                        track.tracking_id,
                    )
            self._last_positions[track.tracking_id] = track.centroid
            self._last_seen_frame[track.tracking_id] = self._frame_number
        self._remove_inactive_tracks()
        return events

    def reset(self) -> None:
        """Clear positions and event de-duplication state."""
        self._last_positions.clear()
        self._last_seen_frame.clear()
        self._emitted_events.clear()
        self._frame_number = 0

    def _crossing_type(self, previous: Point, current: Point) -> CrossingType | None:
        if self._config.line_type == "polygon":
            was_inside = _point_in_polygon(previous, self._config.polygon_points)
            is_inside = _point_in_polygon(current, self._config.polygon_points)
            if not was_inside and is_inside:
                return CrossingType.ENTER
            if was_inside and not is_inside:
                return CrossingType.EXIT
            return None

        if self._config.line_type == "horizontal":
            crossed = _opposite_sides(previous[1], current[1], self._config.position)
            direction = "down" if current[1] > previous[1] else "up"
        else:
            crossed = _opposite_sides(previous[0], current[0], self._config.position)
            direction = "right" if current[0] > previous[0] else "left"
        if not crossed:
            return None
        return CrossingType.ENTER if direction == self._config.enter_direction else CrossingType.EXIT

    def _remove_inactive_tracks(self) -> None:
        expiry_frame = self._frame_number - self._config.max_inactive_frames
        inactive_ids = [track_id for track_id, frame in self._last_seen_frame.items() if frame < expiry_frame]
        for track_id in inactive_ids:
            self._last_seen_frame.pop(track_id, None)
            self._last_positions.pop(track_id, None)
            self._emitted_events.discard((track_id, CrossingType.ENTER))
            self._emitted_events.discard((track_id, CrossingType.EXIT))

    @staticmethod
    def _load_settings() -> Any:
        from app.config.settings import get_settings

        return get_settings()


def _opposite_sides(previous: float, current: float, position: float | None) -> bool:
    assert position is not None
    return (previous < position < current) or (current < position < previous)


def _parse_polygon_points(raw_points: str) -> tuple[Point, ...]:
    if not raw_points.strip():
        return ()
    try:
        return tuple(
            (float(x), float(y))
            for pair in raw_points.split(";")
            for x, y in [pair.strip().split(",")]
        )
    except ValueError as error:
        raise ValueError("CROSSING_POLYGON_POINTS must have format 'x,y;x,y;x,y'") from error


def _point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Return whether a point is inside a polygon using ray casting."""
    x, y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        intersects = (current_y > y) != (previous_y > y) and x < (
            (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
        )
        if intersects:
            inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside
