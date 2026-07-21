from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    rtsp_url: str = Field(min_length=1)
    enabled: bool = True
    location: str | None = Field(default=None, max_length=150)
    building: str | None = Field(default=None, max_length=100)
    floor: str | None = Field(default=None, max_length=50)
    zone: str | None = Field(default=None, max_length=100)
    display_order: int = Field(default=0, ge=0)


class CameraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    location: str | None
    building: str | None
    floor: str | None
    zone: str | None
    status: str
    last_frame_at: datetime | None
    last_error: str | None
    worker_id: str | None
    display_order: int
    created_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tracking_id: UUID
    event_type: str
    line_id: str
    centroid: dict[str, float]
    occurred_at: datetime
    snapshot_url: str | None = None
    camera_id: UUID | None = None
    camera_name: str | None = None
    camera_location: str | None = None


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    reid_key: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    image_path: str
    metadata_path: str
    bbox: dict[str, float]
    saved_at: datetime


class StatisticsResponse(BaseModel):
    enter_count: int
    exit_count: int
    total_events: int
    total_persons: int
    total_cameras: int
    total_snapshots: int
    current_person_count: int
