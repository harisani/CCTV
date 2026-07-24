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
    hysteresis_ratio: float = 0.01
    event_cooldown_frames: int = 3
    enabled: bool = True
    normalized: bool = False
    virtual_line_id: UUID | None = None
    from_zone_id: UUID | None = None
    to_zone_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.line_id.strip():
            raise ValueError("line_id must not be empty")
        if not self.enabled:
            return
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
        if not 0 <= self.hysteresis_ratio <= 0.25:
            raise ValueError("hysteresis_ratio must be between zero and 0.25")
        if self.event_cooldown_frames < 0:
            raise ValueError("event_cooldown_frames must not be negative")

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
            hysteresis_ratio=settings.crossing_hysteresis_ratio,
            event_cooldown_frames=settings.crossing_event_cooldown_frames,
        )

    @classmethod
    def from_mapping(
        cls,
        value: dict[str, Any],
        *,
        max_inactive_frames: int = 300,
        hysteresis_ratio: float = 0.01,
        event_cooldown_frames: int = 3,
    ) -> "VirtualLineConfig":
        return cls(
            line_id=str(value.get("line_id", "main-door")),
            line_type=value.get("line_type", "horizontal"),
            position=value.get("position"),
            enter_direction=value.get("enter_direction", "down"),
            polygon_points=tuple(
                (float(point["x"]), float(point["y"]))
                for point in value.get("polygon_points", [])
            ),
            max_inactive_frames=max_inactive_frames,
            hysteresis_ratio=hysteresis_ratio,
            event_cooldown_frames=event_cooldown_frames,
            enabled=bool(value.get("enabled", True)),
            normalized=True,
            virtual_line_id=_optional_uuid(value.get("virtual_line_id")),
            from_zone_id=_optional_uuid(value.get("from_zone_id")),
            to_zone_id=_optional_uuid(value.get("to_zone_id")),
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
    virtual_line_id: UUID | None = None
    origin_zone_id: UUID | None = None
    destination_zone_id: UUID | None = None


class CrossingService:
    """Create ENTER/EXIT events from tracked people crossing one virtual line."""

    def __init__(self, config: VirtualLineConfig | None = None, *, settings: Any | None = None) -> None:
        if config is not None and settings is not None:
            raise ValueError("Pass either config or settings, not both")
        if config is None:
            config = VirtualLineConfig.from_settings(settings or self._load_settings())
        self._config = config
        self._stable_sides: dict[int, int] = {}
        self._last_seen_frame: dict[int, int] = {}
        self._last_event_frame: dict[int, int] = {}
        self._frame_number = 0
        self._frame_size: tuple[int, int] | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def config(self) -> VirtualLineConfig:
        return self._config

    def process(
        self,
        tracks: Sequence[TrackedDetection],
        *,
        occurred_at: datetime | None = None,
    ) -> list[CrossingEvent]:
        """Evaluate current tracks and return only new crossing events."""
        self._frame_number += 1
        if not self._config.enabled:
            return []
        events: list[CrossingEvent] = []
        for track in tracks:
            current_side = self._stable_side(track.centroid)
            previous_side = self._stable_sides.get(track.tracking_id)
            if current_side != 0:
                cooldown_elapsed = (
                    self._frame_number - self._last_event_frame.get(track.tracking_id, -10_000)
                    > self._config.event_cooldown_frames
                )
                if previous_side is not None and previous_side != current_side and cooldown_elapsed:
                    event_type = self._crossing_type(previous_side, current_side)
                    event = CrossingEvent(
                        event_id=uuid4(),
                        event_type=event_type,
                        line_id=self._config.line_id,
                        tracking_id=track.tracking_id,
                        centroid=track.centroid,
                        occurred_at=occurred_at or datetime.now(UTC),
                        virtual_line_id=self._config.virtual_line_id,
                        origin_zone_id=(
                            self._config.from_zone_id
                            if event_type == CrossingType.ENTER
                            else self._config.to_zone_id
                        ),
                        destination_zone_id=(
                            self._config.to_zone_id
                            if event_type == CrossingType.ENTER
                            else self._config.from_zone_id
                        ),
                    )
                    self._last_event_frame[track.tracking_id] = self._frame_number
                    events.append(event)
                    self._logger.info(
                        "Crossing event=%s line=%s tracking_id=%s",
                        event_type,
                        self._config.line_id,
                        track.tracking_id,
                    )
                    self._stable_sides[track.tracking_id] = current_side
                elif previous_side is None:
                    self._stable_sides[track.tracking_id] = current_side
                elif previous_side == current_side:
                    self._stable_sides[track.tracking_id] = current_side
            self._last_seen_frame[track.tracking_id] = self._frame_number
        self._remove_inactive_tracks()
        return events

    def reset(self) -> None:
        """Clear positions and event de-duplication state."""
        self._stable_sides.clear()
        self._last_seen_frame.clear()
        self._last_event_frame.clear()
        self._frame_number = 0

    def set_frame_size(self, width: int, height: int) -> None:
        """Set the current source resolution used by normalized configurations."""
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be greater than zero")
        self._frame_size = (width, height)

    def _stable_side(self, centroid: Point) -> int:
        if self._config.line_type == "polygon":
            return 1 if _point_in_polygon(centroid, self._scaled_polygon()) else -1
        position = self._scaled_position()
        assert position is not None
        value = centroid[1] if self._config.line_type == "horizontal" else centroid[0]
        margin = self._scaled_hysteresis()
        if value < position - margin:
            return -1
        if value > position + margin:
            return 1
        return 0

    def _crossing_type(self, previous_side: int, current_side: int) -> CrossingType:
        if self._config.line_type == "polygon":
            return CrossingType.ENTER if current_side == 1 else CrossingType.EXIT
        positive_direction = "down" if self._config.line_type == "horizontal" else "right"
        direction = positive_direction if current_side > previous_side else (
            "up" if self._config.line_type == "horizontal" else "left"
        )
        return CrossingType.ENTER if direction == self._config.enter_direction else CrossingType.EXIT

    def _scaled_hysteresis(self) -> float:
        if self._frame_size is None:
            return 0.0
        width, height = self._frame_size
        dimension = height if self._config.line_type == "horizontal" else width
        return dimension * self._config.hysteresis_ratio

    def _scaled_position(self) -> float | None:
        position = self._config.position
        if position is None or not self._config.normalized:
            return position
        if self._frame_size is None:
            raise RuntimeError("frame size must be set before processing normalized geometry")
        width, height = self._frame_size
        dimension = height if self._config.line_type == "horizontal" else width
        return position * dimension

    def _scaled_polygon(self) -> tuple[Point, ...]:
        if not self._config.normalized:
            return self._config.polygon_points
        if self._frame_size is None:
            raise RuntimeError("frame size must be set before processing normalized geometry")
        width, height = self._frame_size
        return tuple((x * width, y * height) for x, y in self._config.polygon_points)

    def _remove_inactive_tracks(self) -> None:
        expiry_frame = self._frame_number - self._config.max_inactive_frames
        inactive_ids = [track_id for track_id, frame in self._last_seen_frame.items() if frame < expiry_frame]
        for track_id in inactive_ids:
            self._last_seen_frame.pop(track_id, None)
            self._stable_sides.pop(track_id, None)
            self._last_event_frame.pop(track_id, None)

    @staticmethod
    def _load_settings() -> Any:
        from app.config.settings import get_settings

        return get_settings()


class MultiLineCrossingService:
    """Evaluate isolated crossing state for every configured camera line."""

    def __init__(self, configs: Sequence[VirtualLineConfig]) -> None:
        line_ids = [config.line_id for config in configs]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("line_id must be unique within one camera")
        self._services = tuple(CrossingService(config) for config in configs)

    @property
    def configs(self) -> tuple[VirtualLineConfig, ...]:
        return tuple(service.config for service in self._services)

    def process(
        self,
        tracks: Sequence[TrackedDetection],
        *,
        occurred_at: datetime | None = None,
    ) -> list[CrossingEvent]:
        events: list[CrossingEvent] = []
        for service in self._services:
            events.extend(
                service.process(tracks, occurred_at=occurred_at)
            )
        return events

    def reset(self) -> None:
        for service in self._services:
            service.reset()

    def set_frame_size(self, width: int, height: int) -> None:
        for service in self._services:
            service.set_frame_size(width, height)


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


def _optional_uuid(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


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
