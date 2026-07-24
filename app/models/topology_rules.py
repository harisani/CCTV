"""Transport-independent validation rules for topology geometry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.models.entities import VirtualLineType


def validate_virtual_line_geometry(
    line_type: VirtualLineType,
    position: float | None,
    points: Sequence[Any] | None,
    enter_direction: str,
    from_zone_id: UUID | None,
    to_zone_id: UUID | None,
) -> None:
    if from_zone_id is not None and from_zone_id == to_zone_id:
        raise ValueError("from_zone_id and to_zone_id must be different")
    if line_type in {VirtualLineType.HORIZONTAL, VirtualLineType.VERTICAL}:
        if position is None:
            raise ValueError("position is required for horizontal and vertical lines")
    elif points is None or len(points) < 3:
        raise ValueError("polygon virtual line requires at least three points")
    if line_type == VirtualLineType.HORIZONTAL and enter_direction not in {"up", "down"}:
        raise ValueError("horizontal line direction must be up or down")
    if line_type == VirtualLineType.VERTICAL and enter_direction not in {"left", "right"}:
        raise ValueError("vertical line direction must be left or right")
