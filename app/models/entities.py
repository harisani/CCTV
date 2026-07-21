"""PostgreSQL ORM entities for cameras, identities, tracks, events, and snapshots."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class EventType(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


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
