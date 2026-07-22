from datetime import date, datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlparse
from app.models import BackupSource, BackupStatus, UserRole

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=12, max_length=256)
    role: UserRole
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    role: UserRole | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    rtsp_url: str = Field(min_length=1)
    enabled: bool = True
    location: str | None = Field(default=None, max_length=150)
    building: str | None = Field(default=None, max_length=100)
    floor: str | None = Field(default=None, max_length=50)
    zone: str | None = Field(default=None, max_length=100)
    display_order: int = Field(default=0, ge=0)

    @field_validator("rtsp_url")
    @classmethod
    def validate_video_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme.lower() not in {"rtsp", "rtsps", "http", "https"} or not parsed.hostname:
            raise ValueError("Camera URL must use rtsp, rtsps, http, or https and include a host")
        return value.strip()


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rtsp_url: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    location: str | None = Field(default=None, max_length=150)
    building: str | None = Field(default=None, max_length=100)
    floor: str | None = Field(default=None, max_length=50)
    zone: str | None = Field(default=None, max_length=100)
    display_order: int | None = Field(default=None, ge=0)

    @field_validator("rtsp_url")
    @classmethod
    def validate_video_url(cls, value: str | None) -> str | None:
        return CameraCreate.validate_video_url(value) if value is not None else None


class CameraConnectionTest(BaseModel):
    rtsp_url: str = Field(min_length=1)

    @field_validator("rtsp_url")
    @classmethod
    def validate_video_url(cls, value: str) -> str:
        return CameraCreate.validate_video_url(value)


class CameraConnectionResult(BaseModel):
    connected: bool
    latency_ms: int
    width: int | None = None
    height: int | None = None
    detail: str


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


class BackupCreate(BaseModel):
    backup_date: date | None = None


class BackupArchiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: BackupSource
    status: BackupStatus
    backup_date: date
    original_filename: str | None
    checksum_sha256: str | None
    size_bytes: int | None
    schema_version: int
    record_counts: dict[str, int] | None
    error_message: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    completed_at: datetime | None


class ArchiveRecordPage(BaseModel):
    items: list[dict]
    total: int
    offset: int
    limit: int
    entity: str
