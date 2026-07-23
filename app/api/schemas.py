from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlparse
from app.models import (
    AccessDirection,
    AccessEventStatus,
    BackupSource,
    BackupStatus,
    DisasterRecoveryStatus,
    RFIDCardStatus,
    RFIDReaderDirection,
    UserRole,
)

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


class EmployeeCreate(BaseModel):
    employee_number: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9._/-]+$",
    )
    full_name: str = Field(min_length=2, max_length=150)
    department: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @field_validator("employee_number", "full_name", mode="before")
    @classmethod
    def strip_required_employee_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("department")
    @classmethod
    def normalize_optional_department(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class EmployeeUpdate(BaseModel):
    employee_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9._/-]+$",
    )
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    department: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None

    @field_validator("employee_number", "full_name", mode="before")
    @classmethod
    def strip_optional_employee_fields(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("department")
    @classmethod
    def normalize_optional_department(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @model_validator(mode="after")
    def validate_employee_changes(self) -> "EmployeeUpdate":
        if not self.model_fields_set:
            raise ValueError("Kirim minimal satu perubahan data pegawai")
        for field in ("employee_number", "full_name", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} tidak boleh null")
        return self


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_number: str
    full_name: str
    department: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeImportResponse(BaseModel):
    imported_count: int
    total_rows: int


class RFIDCardCreate(BaseModel):
    card_number: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9:_-]+$",
    )
    label: str | None = Field(default=None, max_length=120)
    status: RFIDCardStatus = RFIDCardStatus.ACTIVE
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator("card_number", mode="before")
    @classmethod
    def normalize_card_number(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("label")
    @classmethod
    def normalize_card_label(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Timestamp kartu harus menyertakan zona waktu")
        return value

    @model_validator(mode="after")
    def validate_card_window(self) -> "RFIDCardCreate":
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("Masa berlaku akhir tidak boleh sebelum tanggal mulai")
        return self


class RFIDCardUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    status: RFIDCardStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator("label")
    @classmethod
    def normalize_card_label(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Timestamp kartu harus menyertakan zona waktu")
        return value

    @model_validator(mode="after")
    def validate_card_changes(self) -> "RFIDCardUpdate":
        if not self.model_fields_set:
            raise ValueError("Kirim minimal satu perubahan kartu RFID")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status kartu tidak boleh null")
        return self


class RFIDCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    card_number: str
    label: str | None
    status: RFIDCardStatus
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime
    updated_at: datetime


class RFIDSimulatorTapRequest(BaseModel):
    card_number: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9:_-]+$",
    )
    direction: AccessDirection
    occurred_at: datetime | None = None
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=120,
        pattern=r"^[a-zA-Z0-9._:-]+$",
    )

    @field_validator("card_number", mode="before")
    @classmethod
    def normalize_simulated_card_number(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def normalize_idempotency_key(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @field_validator("occurred_at")
    @classmethod
    def require_simulator_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at harus menyertakan zona waktu")
        return value


class RFIDSimulatorReaderResponse(BaseModel):
    code: str
    name: str
    location: str | None
    direction: RFIDReaderDirection


class RFIDSimulatorCardOption(BaseModel):
    card_number: str
    label: str | None
    employee_id: UUID
    employee_number: str
    employee_name: str
    department: str | None


class RFIDSimulatorOptionsResponse(BaseModel):
    enabled: bool
    reader: RFIDSimulatorReaderResponse
    cards: list[RFIDSimulatorCardOption]
    event_ttl_seconds: int


class RFIDAccessEventResponse(BaseModel):
    id: UUID
    external_event_id: str
    reader_code: str
    reader_name: str
    card_number: str
    card_id: UUID | None
    employee_id: UUID | None
    employee_number: str | None
    employee_name: str | None
    direction: AccessDirection
    status: AccessEventStatus
    status_reason: str | None
    occurred_at: datetime
    expires_at: datetime
    simulated: bool


class RFIDSimulatorTapResponse(BaseModel):
    created: bool
    event: RFIDAccessEventResponse


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


class CrossingPoint(BaseModel):
    """Resolution-independent point expressed as a fraction of the video frame."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CameraCrossingConfig(BaseModel):
    enabled: bool = True
    line_id: str = Field(default="main-door", min_length=1, max_length=100)
    line_type: Literal["horizontal", "vertical", "polygon"] = "horizontal"
    position: float | None = Field(default=0.5, ge=0, le=1)
    enter_direction: Literal["up", "down", "left", "right"] = "down"
    polygon_points: list[CrossingPoint] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_geometry(self) -> "CameraCrossingConfig":
        if not self.enabled:
            return self
        if self.line_type in {"horizontal", "vertical"} and self.position is None:
            raise ValueError("position is required for a horizontal or vertical line")
        if self.line_type == "horizontal" and self.enter_direction not in {"up", "down"}:
            raise ValueError("horizontal line direction must be up or down")
        if self.line_type == "vertical" and self.enter_direction not in {"left", "right"}:
            raise ValueError("vertical line direction must be left or right")
        if self.line_type == "polygon" and len(self.polygon_points) < 3:
            raise ValueError("polygon requires at least three points")
        return self


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
    crossing_config: CameraCrossingConfig | None = None
    created_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tracking_id: UUID
    byte_track_id: int | None = None
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
    is_active: bool
    needs_review: bool
    merged_into_person_id: UUID | None
    identity_version: int
    embedding_count: int = 0
    tracking_count: int = 0
    first_seen_at: datetime
    last_seen_at: datetime


class PersonMergeRequest(BaseModel):
    target_person_id: UUID
    source_person_ids: list[UUID] = Field(min_length=1, max_length=50)


class PersonSplitRequest(BaseModel):
    tracking_ids: list[UUID] = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, max_length=100)


class PersonTrackingResponse(BaseModel):
    id: UUID
    camera_id: UUID
    byte_track_id: int
    started_at: datetime
    ended_at: datetime | None
    is_active: bool
    embedding_count: int
    event_count: int


class ReIdConfigurationResponse(BaseModel):
    similarity_threshold: float
    ambiguity_margin: float
    minimum_quality: float
    retention_days: int
    minimum_templates_per_person: int
    maximum_templates_per_person: int


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
    confirmed_person_count: int
    uncertain_person_count: int


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


class DisasterRecoveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: DisasterRecoveryStatus
    checksum_sha256: str | None
    size_bytes: int | None
    manifest: dict | None
    offsite_path: str | None
    offsite_checksum_sha256: str | None
    restore_database: str | None
    error_message: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    completed_at: datetime | None


class DisasterRecoveryRestore(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)
