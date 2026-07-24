"""PostgreSQL ORM entities for cameras, identities, tracks, events, and snapshots."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database.base import Base


class EventType(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class CaptureEventStatus(StrEnum):
    CAPTURED = "CAPTURED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    NEED_REVIEW = "NEED_REVIEW"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


class EvidenceAssetType(StrEnum):
    ORIGINAL_SNAPSHOT = "ORIGINAL_SNAPSHOT"
    ANNOTATED_SNAPSHOT = "ANNOTATED_SNAPSHOT"
    FACE_CROP = "FACE_CROP"
    PERIOCULAR_CROP = "PERIOCULAR_CROP"
    FULL_BODY = "FULL_BODY"
    THUMBNAIL = "THUMBNAIL"
    VIDEO_CLIP = "VIDEO_CLIP"
    METADATA_JSON = "METADATA_JSON"


class EvidenceIntegrityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"


class PresenceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    UNCERTAIN = "UNCERTAIN"
    CLOSED = "CLOSED"


class UserRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"


class CameraRoleType(StrEnum):
    IDENTITY_CAPTURE = "IDENTITY_CAPTURE"
    TRANSITION = "TRANSITION"
    OVERVIEW = "OVERVIEW"
    EVIDENCE = "EVIDENCE"


class ZoneSensitivity(StrEnum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    CRITICAL = "CRITICAL"


class ProcessingPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class VirtualLineType(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    POLYGON = "polygon"


class BackupSource(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class BackupStatus(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    FAILED = "FAILED"


class DisasterRecoveryStatus(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    RESTORING = "RESTORING"
    RESTORED = "RESTORED"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class BackupArchive(Base):
    __tablename__ = "backup_archives"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[BackupSource] = mapped_column(Enum(BackupSource, name="backup_source"), index=True)
    status: Mapped[BackupStatus] = mapped_column(Enum(BackupStatus, name="backup_status"), index=True)
    backup_date: Mapped[date] = mapped_column(Date, index=True)
    schedule_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text, unique=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    record_counts: Mapped[dict[str, int] | None] = mapped_column(JSON)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisasterRecoveryArchive(Base):
    __tablename__ = "disaster_recovery_archives"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    status: Mapped[DisasterRecoveryStatus] = mapped_column(
        Enum(DisasterRecoveryStatus, name="disaster_recovery_status"), index=True
    )
    schedule_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    file_path: Mapped[str] = mapped_column(Text, unique=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    offsite_path: Mapped[str | None] = mapped_column(Text)
    offsite_checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    restore_database: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Jakarta")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    zones: Mapped[list[Zone]] = relationship(
        back_populates="building", cascade="all, delete-orphan"
    )


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("building_id", "code", name="uq_zone_building_code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    building_id: Mapped[UUID] = mapped_column(
        ForeignKey("buildings.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    floor_name: Mapped[str | None] = mapped_column(String(80), index=True)
    area_name: Mapped[str | None] = mapped_column(String(120), index=True)
    room_name: Mapped[str | None] = mapped_column(String(120), index=True)
    roi_polygon: Mapped[list[dict[str, float]] | None] = mapped_column(JSON)
    sensitivity: Mapped[ZoneSensitivity] = mapped_column(
        Enum(ZoneSensitivity, name="zone_sensitivity"),
        default=ZoneSensitivity.STANDARD,
        index=True,
    )
    processing_priority: Mapped[ProcessingPriority] = mapped_column(
        Enum(ProcessingPriority, name="processing_priority"),
        default=ProcessingPriority.NORMAL,
        index=True,
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    building: Mapped[Building] = relationship(back_populates="zones")
    camera_mappings: Mapped[list[CameraZoneMapping]] = relationship(
        back_populates="zone", cascade="all, delete-orphan"
    )


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    rtsp_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[str | None] = mapped_column(String(150), index=True)
    building: Mapped[str | None] = mapped_column(String(100), index=True)
    floor: Mapped[str | None] = mapped_column(String(50), index=True)
    zone: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default="OFFLINE", index=True)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(100), index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    crossing_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    trackings: Mapped[list[Tracking]] = relationship(back_populates="camera", cascade="all, delete-orphan")
    presence_sessions: Mapped[list[PresenceSession]] = relationship(back_populates="camera")
    roles: Mapped[list[CameraRole]] = relationship(
        back_populates="camera", cascade="all, delete-orphan"
    )
    zone_mappings: Mapped[list[CameraZoneMapping]] = relationship(
        back_populates="camera", cascade="all, delete-orphan"
    )
    virtual_lines: Mapped[list[VirtualLine]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        order_by="VirtualLine.display_order",
    )


class CameraRole(Base):
    __tablename__ = "camera_roles"
    __table_args__ = (UniqueConstraint("camera_id", "role", name="uq_camera_role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[CameraRoleType] = mapped_column(
        Enum(CameraRoleType, name="camera_role_type"), index=True
    )
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    camera: Mapped[Camera] = relationship(back_populates="roles")


class CameraZoneMapping(Base):
    __tablename__ = "camera_zone_mappings"
    __table_args__ = (
        UniqueConstraint("camera_id", "zone_id", name="uq_camera_zone_mapping"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    zone_id: Mapped[UUID] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"), index=True
    )
    coverage_polygon: Mapped[list[dict[str, float]] | None] = mapped_column(JSON)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    camera: Mapped[Camera] = relationship(back_populates="zone_mappings")
    zone: Mapped[Zone] = relationship(back_populates="camera_mappings")


class ZoneAdjacency(Base):
    __tablename__ = "zone_adjacencies"
    __table_args__ = (
        UniqueConstraint(
            "source_zone_id", "target_zone_id", name="uq_zone_adjacency_direction"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_zone_id: Mapped[UUID] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"), index=True
    )
    target_zone_id: Mapped[UUID] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"), index=True
    )
    minimum_travel_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    maximum_travel_seconds: Mapped[float] = mapped_column(Float, default=300.0)
    bidirectional: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    source_zone: Mapped[Zone] = relationship(foreign_keys=[source_zone_id])
    target_zone: Mapped[Zone] = relationship(foreign_keys=[target_zone_id])


class VirtualLine(Base):
    __tablename__ = "virtual_lines"
    __table_args__ = (
        UniqueConstraint("camera_id", "line_key", name="uq_virtual_line_camera_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    line_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(150))
    line_type: Mapped[VirtualLineType] = mapped_column(
        Enum(VirtualLineType, name="virtual_line_type"), index=True
    )
    position: Mapped[float | None] = mapped_column(Float)
    points: Mapped[list[dict[str, float]] | None] = mapped_column(JSON)
    enter_direction: Mapped[str] = mapped_column(String(10))
    from_zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"), index=True
    )
    to_zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"), index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    camera: Mapped[Camera] = relationship(back_populates="virtual_lines")
    from_zone: Mapped[Zone | None] = relationship(foreign_keys=[from_zone_id])
    to_zone: Mapped[Zone | None] = relationship(foreign_keys=[to_zone_id])


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str | None] = mapped_column(String(100), index=True)
    reid_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    reid_embedding: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    merged_into_person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), index=True
    )
    identity_version: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    trackings: Mapped[list[Tracking]] = relationship(back_populates="person")
    embeddings: Mapped[list[PersonEmbedding]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    merged_into: Mapped[Person | None] = relationship(remote_side="Person.id")
    presence_sessions: Mapped[list[PresenceSession]] = relationship(back_populates="person")


class PersonEmbedding(Base):
    __tablename__ = "person_embeddings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    tracking_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trackings.id", ondelete="SET NULL"), index=True
    )
    camera_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(100), index=True)
    dimension: Mapped[int] = mapped_column(Integer, default=512)
    embedding: Mapped[list[float]] = mapped_column(Vector(512))
    quality_score: Mapped[float] = mapped_column(default=1.0, index=True)
    match_similarity: Mapped[float | None] = mapped_column()
    match_decision: Mapped[str] = mapped_column(String(30), index=True)
    matched_embedding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("person_embeddings.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    person: Mapped[Person] = relationship(back_populates="embeddings")


class Tracking(Base):
    __tablename__ = "trackings"
    __table_args__ = (UniqueConstraint("camera_id", "byte_track_id", "started_at", name="uq_tracking_camera_track_started"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    byte_track_id: Mapped[int] = mapped_column(Integer, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_centroid: Mapped[dict[str, float] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    camera: Mapped[Camera] = relationship(back_populates="trackings")
    person: Mapped[Person | None] = relationship(back_populates="trackings")
    events: Mapped[list[Event]] = relationship(back_populates="tracking", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tracking_id: Mapped[UUID] = mapped_column(ForeignKey("trackings.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, name="event_type"), index=True)
    line_id: Mapped[str] = mapped_column(String(100), index=True)
    centroid: Mapped[dict[str, float]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    tracking: Mapped[Tracking] = relationship(back_populates="events")
    snapshot: Mapped[Snapshot | None] = relationship(back_populates="event", cascade="all, delete-orphan", uselist=False)
    capture_event: Mapped[CaptureEvent | None] = relationship(
        back_populates="source_event", uselist=False
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True, index=True)
    image_path: Mapped[str] = mapped_column(Text)
    metadata_path: Mapped[str] = mapped_column(Text)
    bbox: Mapped[dict[str, float]] = mapped_column(JSON)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    event: Mapped[Event] = relationship(back_populates="snapshot")
    evidence_assets: Mapped[list[EvidenceAsset]] = relationship(
        back_populates="legacy_snapshot"
    )


class CaptureEvent(Base):
    """Immutable capture envelope created before asynchronous AI processing."""

    __tablename__ = "capture_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    source_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), unique=True
    )
    camera_id: Mapped[UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"), index=True
    )
    zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"), index=True
    )
    virtual_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("virtual_lines.id", ondelete="SET NULL"), index=True
    )
    tracking_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trackings.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[CaptureEventStatus] = mapped_column(
        Enum(CaptureEventStatus, name="capture_event_status"),
        default=CaptureEventStatus.CAPTURED,
        index=True,
    )
    direction: Mapped[str | None] = mapped_column(String(20), index=True)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON)
    centroid: Mapped[dict[str, float] | None] = mapped_column(JSON)
    capture_quality: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    capture_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    source_event: Mapped[Event | None] = relationship(back_populates="capture_event")
    camera: Mapped[Camera] = relationship()
    zone: Mapped[Zone | None] = relationship()
    virtual_line: Mapped[VirtualLine | None] = relationship()
    tracking: Mapped[Tracking | None] = relationship()
    evidence_assets: Mapped[list[EvidenceAsset]] = relationship(
        back_populates="capture_event",
        cascade="all, delete-orphan",
        order_by="EvidenceAsset.sequence_index",
    )


class EvidenceAsset(Base):
    """Content-addressed metadata for an immutable evidence object."""

    __tablename__ = "evidence_assets"
    __table_args__ = (
        UniqueConstraint(
            "capture_event_id",
            "asset_type",
            "sequence_index",
            name="uq_evidence_capture_type_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    capture_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("capture_events.id", ondelete="CASCADE"), index=True
    )
    legacy_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"), index=True
    )
    asset_type: Mapped[EvidenceAssetType] = mapped_column(
        Enum(EvidenceAssetType, name="evidence_asset_type"), index=True
    )
    sequence_index: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    integrity_status: Mapped[EvidenceIntegrityStatus] = mapped_column(
        Enum(EvidenceIntegrityStatus, name="evidence_integrity_status"),
        default=EvidenceIntegrityStatus.VERIFIED,
        index=True,
    )
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    asset_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    capture_event: Mapped[CaptureEvent] = relationship(
        back_populates="evidence_assets"
    )
    legacy_snapshot: Mapped[Snapshot | None] = relationship(
        back_populates="evidence_assets"
    )


class PresenceSession(Base):
    """Persisted room presence opened by ENTER and closed only by EXIT/reconciliation."""

    __tablename__ = "presence_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), index=True
    )
    camera_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    entry_tracking_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trackings.id", ondelete="SET NULL"), index=True
    )
    exit_tracking_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trackings.id", ondelete="SET NULL"), index=True
    )
    entry_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), unique=True, index=True
    )
    exit_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), unique=True, index=True
    )
    status: Mapped[PresenceStatus] = mapped_column(
        Enum(PresenceStatus, name="presence_status"), default=PresenceStatus.ACTIVE, index=True
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    uncertain_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    person: Mapped[Person | None] = relationship(back_populates="presence_sessions")
    camera: Mapped[Camera | None] = relationship(back_populates="presence_sessions")
