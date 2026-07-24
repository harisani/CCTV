"""Validated API contracts for factory topology configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    CameraRoleType,
    ProcessingPriority,
    VirtualLineType,
    ZoneSensitivity,
)
from app.models.topology_rules import validate_virtual_line_geometry


class NormalizedPoint(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class BuildingCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=150)
    address: str | None = Field(default=None, max_length=1000)
    timezone: str = Field(default="Asia/Jakarta", min_length=1, max_length=64)
    enabled: bool = True


class BuildingUpdate(BaseModel):
    code: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=150)
    address: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "BuildingUpdate":
        _reject_explicit_null(self, {"code", "name", "timezone", "enabled"})
        return self


class BuildingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    address: str | None
    timezone: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ZoneCreate(BaseModel):
    building_id: UUID
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=150)
    floor_name: str | None = Field(default=None, max_length=80)
    area_name: str | None = Field(default=None, max_length=120)
    room_name: str | None = Field(default=None, max_length=120)
    roi_polygon: list[NormalizedPoint] | None = Field(default=None, max_length=100)
    sensitivity: ZoneSensitivity = ZoneSensitivity.STANDARD
    processing_priority: ProcessingPriority = ProcessingPriority.NORMAL
    retention_days: int = Field(default=90, ge=1, le=3650)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_roi(self) -> "ZoneCreate":
        if self.roi_polygon is not None and len(self.roi_polygon) < 3:
            raise ValueError("roi_polygon requires at least three points")
        return self


class ZoneUpdate(BaseModel):
    building_id: UUID | None = None
    code: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=150)
    floor_name: str | None = Field(default=None, max_length=80)
    area_name: str | None = Field(default=None, max_length=120)
    room_name: str | None = Field(default=None, max_length=120)
    roi_polygon: list[NormalizedPoint] | None = Field(default=None, max_length=100)
    sensitivity: ZoneSensitivity | None = None
    processing_priority: ProcessingPriority | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_roi(self) -> "ZoneUpdate":
        _reject_explicit_null(
            self,
            {
                "building_id",
                "code",
                "name",
                "sensitivity",
                "processing_priority",
                "retention_days",
                "enabled",
            },
        )
        if self.roi_polygon is not None and len(self.roi_polygon) < 3:
            raise ValueError("roi_polygon requires at least three points")
        return self


class ZoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    building_id: UUID
    code: str
    name: str
    floor_name: str | None
    area_name: str | None
    room_name: str | None
    roi_polygon: list[NormalizedPoint] | None
    sensitivity: ZoneSensitivity
    processing_priority: ProcessingPriority
    retention_days: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CameraRoleCreate(BaseModel):
    camera_id: UUID
    role: CameraRoleType
    configuration: dict[str, Any] | None = None
    enabled: bool = True


class CameraRoleUpdate(BaseModel):
    configuration: dict[str, Any] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "CameraRoleUpdate":
        _reject_explicit_null(self, {"enabled"})
        return self


class CameraRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    camera_id: UUID
    role: CameraRoleType
    configuration: dict[str, Any] | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CameraZoneMappingCreate(BaseModel):
    camera_id: UUID
    zone_id: UUID
    coverage_polygon: list[NormalizedPoint] | None = Field(
        default=None, max_length=100
    )
    is_primary: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_coverage(self) -> "CameraZoneMappingCreate":
        if self.coverage_polygon is not None and len(self.coverage_polygon) < 3:
            raise ValueError("coverage_polygon requires at least three points")
        return self


class CameraZoneMappingUpdate(BaseModel):
    coverage_polygon: list[NormalizedPoint] | None = Field(
        default=None, max_length=100
    )
    is_primary: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_coverage(self) -> "CameraZoneMappingUpdate":
        _reject_explicit_null(self, {"is_primary", "enabled"})
        if self.coverage_polygon is not None and len(self.coverage_polygon) < 3:
            raise ValueError("coverage_polygon requires at least three points")
        return self


class CameraZoneMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    camera_id: UUID
    zone_id: UUID
    coverage_polygon: list[NormalizedPoint] | None
    is_primary: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ZoneAdjacencyCreate(BaseModel):
    source_zone_id: UUID
    target_zone_id: UUID
    minimum_travel_seconds: float = Field(default=0, ge=0, le=86400)
    maximum_travel_seconds: float = Field(default=300, ge=0, le=86400)
    bidirectional: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def validate_route(self) -> "ZoneAdjacencyCreate":
        if self.source_zone_id == self.target_zone_id:
            raise ValueError("source and target zones must be different")
        if self.maximum_travel_seconds < self.minimum_travel_seconds:
            raise ValueError("maximum travel time must not be below minimum travel time")
        return self


class ZoneAdjacencyUpdate(BaseModel):
    minimum_travel_seconds: float | None = Field(default=None, ge=0, le=86400)
    maximum_travel_seconds: float | None = Field(default=None, ge=0, le=86400)
    bidirectional: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "ZoneAdjacencyUpdate":
        _reject_explicit_null(
            self,
            {
                "minimum_travel_seconds",
                "maximum_travel_seconds",
                "bidirectional",
                "enabled",
            },
        )
        return self


class ZoneAdjacencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_zone_id: UUID
    target_zone_id: UUID
    minimum_travel_seconds: float
    maximum_travel_seconds: float
    bidirectional: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class VirtualLineCreate(BaseModel):
    camera_id: UUID
    line_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    name: str = Field(min_length=1, max_length=150)
    line_type: VirtualLineType
    position: float | None = Field(default=None, ge=0, le=1)
    points: list[NormalizedPoint] | None = Field(default=None, max_length=100)
    enter_direction: Literal["up", "down", "left", "right"]
    from_zone_id: UUID | None = None
    to_zone_id: UUID | None = None
    is_primary: bool = False
    display_order: int = Field(default=0, ge=0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_geometry(self) -> "VirtualLineCreate":
        validate_virtual_line_geometry(
            self.line_type,
            self.position,
            self.points,
            self.enter_direction,
            self.from_zone_id,
            self.to_zone_id,
        )
        return self


class VirtualLineUpdate(BaseModel):
    line_key: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=150)
    line_type: VirtualLineType | None = None
    position: float | None = Field(default=None, ge=0, le=1)
    points: list[NormalizedPoint] | None = Field(default=None, max_length=100)
    enter_direction: Literal["up", "down", "left", "right"] | None = None
    from_zone_id: UUID | None = None
    to_zone_id: UUID | None = None
    is_primary: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "VirtualLineUpdate":
        _reject_explicit_null(
            self,
            {
                "line_key",
                "name",
                "line_type",
                "enter_direction",
                "is_primary",
                "display_order",
                "enabled",
            },
        )
        return self


class VirtualLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    camera_id: UUID
    line_key: str
    name: str
    line_type: VirtualLineType
    position: float | None
    points: list[NormalizedPoint] | None
    enter_direction: str
    from_zone_id: UUID | None
    to_zone_id: UUID | None
    is_primary: bool
    display_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TopologyGraphResponse(BaseModel):
    buildings: list[BuildingResponse]
    zones: list[ZoneResponse]
    camera_mappings: list[CameraZoneMappingResponse]
    adjacencies: list[ZoneAdjacencyResponse]
    virtual_lines: list[VirtualLineResponse]


class TopologyValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


def _reject_explicit_null(model: BaseModel, fields: set[str]) -> None:
    invalid = sorted(
        field
        for field in fields
        if field in model.model_fields_set and getattr(model, field) is None
    )
    if invalid:
        raise ValueError(f"{', '.join(invalid)} cannot be null")
