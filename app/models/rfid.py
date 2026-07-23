"""RFID access-control entities kept separate from CCTV application users."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class RFIDCardStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


class RFIDReaderDirection(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class AccessDirection(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class AccessEventStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class AccessMatchStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class Employee(Base):
    """A monitored employee; deliberately independent from dashboard users."""

    __tablename__ = "employees"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_number: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    department: Mapped[str | None] = mapped_column(String(120), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    cards: Mapped[list[RFIDCard]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    access_events: Mapped[list[AccessEvent]] = relationship(back_populates="employee")


class RFIDCard(Base):
    """A physical RFID credential assigned to exactly one employee."""

    __tablename__ = "rfid_cards"
    __table_args__ = (
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_rfid_cards_valid_window",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    card_number: Mapped[str] = mapped_column(String(128), unique=True)
    label: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[RFIDCardStatus] = mapped_column(
        Enum(RFIDCardStatus, name="rfid_card_status"),
        default=RFIDCardStatus.ACTIVE,
        index=True,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    employee: Mapped[Employee] = relationship(back_populates="cards")
    access_events: Mapped[list[AccessEvent]] = relationship(back_populates="card")


class RFIDReader(Base):
    """A reader endpoint that produces normalized access events."""

    __tablename__ = "rfid_readers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(150), index=True)
    direction: Mapped[RFIDReaderDirection] = mapped_column(
        Enum(RFIDReaderDirection, name="rfid_reader_direction"),
        default=RFIDReaderDirection.BIDIRECTIONAL,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    access_events: Mapped[list[AccessEvent]] = relationship(back_populates="reader")


class AccessEvent(Base):
    """An immutable reader observation plus its evolving camera-verification state."""

    __tablename__ = "access_events"
    __table_args__ = (
        CheckConstraint(
            "expires_at >= occurred_at",
            name="ck_access_events_expiration_window",
        ),
        UniqueConstraint(
            "reader_id",
            "external_event_id",
            name="uq_access_events_reader_external_event",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reader_id: Mapped[UUID] = mapped_column(
        ForeignKey("rfid_readers.id", ondelete="RESTRICT"), index=True
    )
    card_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rfid_cards.id", ondelete="SET NULL"), index=True
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    external_event_id: Mapped[str] = mapped_column(String(160))
    credential_identifier: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[AccessDirection] = mapped_column(
        Enum(AccessDirection, name="access_direction"), index=True
    )
    status: Mapped[AccessEventStatus] = mapped_column(
        Enum(AccessEventStatus, name="access_event_status"),
        default=AccessEventStatus.PENDING,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    reader: Mapped[RFIDReader] = relationship(back_populates="access_events")
    card: Mapped[RFIDCard | None] = relationship(back_populates="access_events")
    employee: Mapped[Employee | None] = relationship(back_populates="access_events")
    camera_matches: Mapped[list[AccessCameraMatch]] = relationship(
        back_populates="access_event", cascade="all, delete-orphan"
    )


class AccessCameraMatch(Base):
    """A candidate or selected association between one RFID tap and a crossing."""

    __tablename__ = "access_camera_matches"
    __table_args__ = (
        CheckConstraint(
            "match_score >= 0.0 AND match_score <= 1.0",
            name="ck_access_camera_matches_score",
        ),
        UniqueConstraint(
            "access_event_id",
            "crossing_event_id",
            name="uq_access_camera_matches_candidate",
        ),
        Index(
            "uq_access_camera_matches_selected_access_event",
            "access_event_id",
            unique=True,
            postgresql_where=text("status = 'SELECTED'"),
        ),
        Index(
            "uq_access_camera_matches_selected_crossing_event",
            "crossing_event_id",
            unique=True,
            postgresql_where=text(
                "status = 'SELECTED' AND crossing_event_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    access_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_events.id", ondelete="CASCADE"), index=True
    )
    camera_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    crossing_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    tracking_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trackings.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[AccessMatchStatus] = mapped_column(
        Enum(AccessMatchStatus, name="access_match_status"),
        default=AccessMatchStatus.CANDIDATE,
        index=True,
    )
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    time_delta_ms: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    access_event: Mapped[AccessEvent] = relationship(back_populates="camera_matches")
    camera: Mapped[Any | None] = relationship("Camera")
    crossing_event: Mapped[Any | None] = relationship("Event")
    tracking: Mapped[Any | None] = relationship("Tracking")
