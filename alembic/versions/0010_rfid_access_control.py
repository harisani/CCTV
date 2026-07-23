"""RFID employees, credentials, readers, and camera match candidates.

Revision ID: 0010_rfid_access_control
Revises: 0009_presence_sessions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_rfid_access_control"
down_revision: str | None = "0009_presence_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    rfid_card_status = sa.Enum(
        "ACTIVE", "BLOCKED", "LOST", "EXPIRED", name="rfid_card_status"
    )
    rfid_reader_direction = sa.Enum(
        "ENTER", "EXIT", "BIDIRECTIONAL", name="rfid_reader_direction"
    )
    access_direction = sa.Enum("ENTER", "EXIT", name="access_direction")
    access_event_status = sa.Enum(
        "PENDING",
        "VERIFIED",
        "UNMATCHED",
        "AMBIGUOUS",
        "EXPIRED",
        "REJECTED",
        name="access_event_status",
    )
    access_match_status = sa.Enum(
        "CANDIDATE", "SELECTED", "REJECTED", name="access_match_status"
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_number", sa.String(length=80), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_number"),
    )
    op.create_index("ix_employees_full_name", "employees", ["full_name"])
    op.create_index("ix_employees_department", "employees", ["department"])
    op.create_index("ix_employees_is_active", "employees", ["is_active"])

    op.create_table(
        "rfid_readers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("location", sa.String(length=150), nullable=True),
        sa.Column("direction", rfid_reader_direction, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_rfid_readers_location", "rfid_readers", ["location"])
    op.create_index("ix_rfid_readers_direction", "rfid_readers", ["direction"])
    op.create_index("ix_rfid_readers_enabled", "rfid_readers", ["enabled"])

    op.create_table(
        "rfid_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("card_number", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("status", rfid_card_status, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_rfid_cards_valid_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_number"),
    )
    op.create_index("ix_rfid_cards_employee_id", "rfid_cards", ["employee_id"])
    op.create_index("ix_rfid_cards_status", "rfid_cards", ["status"])
    op.create_index("ix_rfid_cards_valid_until", "rfid_cards", ["valid_until"])

    op.create_table(
        "access_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reader_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("external_event_id", sa.String(length=160), nullable=False),
        sa.Column("credential_identifier", sa.String(length=128), nullable=False),
        sa.Column("direction", access_direction, nullable=False),
        sa.Column("status", access_event_status, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["rfid_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reader_id"], ["rfid_readers.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "expires_at >= occurred_at",
            name="ck_access_events_expiration_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reader_id",
            "external_event_id",
            name="uq_access_events_reader_external_event",
        ),
    )
    for column in (
        "reader_id",
        "card_id",
        "employee_id",
        "credential_identifier",
        "direction",
        "status",
        "occurred_at",
        "expires_at",
    ):
        op.create_index(f"ix_access_events_{column}", "access_events", [column])

    op.create_table(
        "access_camera_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("access_event_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("crossing_event_id", sa.Uuid(), nullable=True),
        sa.Column("tracking_id", sa.Uuid(), nullable=True),
        sa.Column("status", access_match_status, nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("time_delta_ms", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["access_event_id"], ["access_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["crossing_event_id"], ["events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tracking_id"], ["trackings.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "match_score >= 0.0 AND match_score <= 1.0",
            name="ck_access_camera_matches_score",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "access_event_id",
            "crossing_event_id",
            name="uq_access_camera_matches_candidate",
        ),
    )
    for column in (
        "access_event_id",
        "camera_id",
        "crossing_event_id",
        "tracking_id",
        "status",
    ):
        op.create_index(
            f"ix_access_camera_matches_{column}",
            "access_camera_matches",
            [column],
        )
    op.create_index(
        "uq_access_camera_matches_selected_access_event",
        "access_camera_matches",
        ["access_event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SELECTED'"),
    )
    op.create_index(
        "uq_access_camera_matches_selected_crossing_event",
        "access_camera_matches",
        ["crossing_event_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'SELECTED' AND crossing_event_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_table("access_camera_matches")
    op.drop_table("access_events")
    op.drop_table("rfid_cards")
    op.drop_table("rfid_readers")
    op.drop_table("employees")

    sa.Enum(name="access_match_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="access_event_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="access_direction").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rfid_card_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rfid_reader_direction").drop(op.get_bind(), checkfirst=True)
