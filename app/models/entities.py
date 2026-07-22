"""PostgreSQL ORM entities for cameras, identities, tracks, events, and snapshots."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Date, JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class EventType(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class UserRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"


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


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str | None] = mapped_column(String(100), index=True)
    reid_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    reid_embedding: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    trackings: Mapped[list[Tracking]] = relationship(back_populates="person")


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


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True, index=True)
    image_path: Mapped[str] = mapped_column(Text)
    metadata_path: Mapped[str] = mapped_column(Text)
    bbox: Mapped[dict[str, float]] = mapped_column(JSON)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    event: Mapped[Event] = relationship(back_populates="snapshot")
