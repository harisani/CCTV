"""structured occupancy facts and session projection

Revision ID: 0017_occupancy_engine
Revises: 0016_global_journeys
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_occupancy_engine"
down_revision: str | None = "0016_global_journeys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "EMPLOYEE", "UNKNOWN", "UNRESOLVED",
        name="occupancy_subject_type",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "ACTIVE",
        "TEMPORARILY_LOST",
        "STALE",
        "EXITED",
        "NEED_REVIEW",
        "MANUALLY_CLOSED",
        name="occupancy_session_state",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "ENTER", "EXIT", "TRANSITION", "OBSERVATION",
        name="occupancy_fact_type",
    ).create(bind, checkfirst=True)

    op.create_table(
        "occupancy_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("journey_event_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("origin_zone_id", sa.Uuid(), nullable=True),
        sa.Column("destination_zone_id", sa.Uuid(), nullable=True),
        sa.Column("current_zone_id", sa.Uuid(), nullable=True),
        sa.Column(
            "fact_type", _enum("occupancy_fact_type"), nullable=False
        ),
        sa.Column(
            "subject_type",
            _enum("occupancy_subject_type"),
            nullable=False,
        ),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "external_subject_key", sa.String(160), nullable=True
        ),
        sa.Column(
            "identity_decision",
            _enum("identity_decision"),
            nullable=False,
        ),
        sa.Column("identity_confidence", sa.Float(), nullable=False),
        sa.Column(
            "correlation_decision",
            _enum("journey_correlation_decision"),
            nullable=False,
        ),
        sa.Column("correlation_score", sa.Float(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "fact_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["current_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["destination_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["journey_event_id"],
            ["journey_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["global_journeys.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["origin_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("journey_event_id"),
    )
    for column in (
        "idempotency_key",
        "journey_id",
        "journey_event_id",
        "camera_id",
        "origin_zone_id",
        "destination_zone_id",
        "current_zone_id",
        "fact_type",
        "subject_type",
        "person_id",
        "external_subject_key",
        "identity_decision",
        "correlation_decision",
        "occurred_at",
    ):
        op.create_index(
            f"ix_occupancy_facts_{column}",
            "occupancy_facts",
            [column],
        )

    op.create_table(
        "occupancy_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column(
            "subject_type",
            _enum("occupancy_subject_type"),
            nullable=False,
        ),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "external_subject_key", sa.String(160), nullable=True
        ),
        sa.Column("entry_journey_event_id", sa.Uuid(), nullable=False),
        sa.Column("exit_journey_event_id", sa.Uuid(), nullable=True),
        sa.Column("last_journey_event_id", sa.Uuid(), nullable=False),
        sa.Column("last_camera_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state", _enum("occupancy_session_state"), nullable=False
        ),
        sa.Column(
            "identity_decision",
            _enum("identity_decision"),
            nullable=False,
        ),
        sa.Column(
            "identification_confidence", sa.Float(), nullable=False
        ),
        sa.Column(
            "review_status",
            _enum("identity_review_status"),
            nullable=False,
        ),
        sa.Column(
            "entered_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("state_reason", sa.String(160), nullable=False),
        sa.Column(
            "reconstruction_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "last_seen_at >= entered_at",
            name="ck_occupancy_session_last_seen",
        ),
        sa.CheckConstraint(
            "exited_at IS NULL OR exited_at >= entered_at",
            name="ck_occupancy_session_exit_time",
        ),
        sa.CheckConstraint(
            "identification_confidence BETWEEN 0 AND 1",
            name="ck_occupancy_session_identity_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["entry_journey_event_id"],
            ["journey_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exit_journey_event_id"],
            ["journey_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["global_journeys.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["last_camera_id"], ["cameras.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["last_journey_event_id"],
            ["journey_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_journey_event_id"),
    )
    for column in (
        "journey_id",
        "zone_id",
        "subject_type",
        "person_id",
        "external_subject_key",
        "entry_journey_event_id",
        "exit_journey_event_id",
        "last_journey_event_id",
        "last_camera_id",
        "state",
        "identity_decision",
        "review_status",
        "entered_at",
        "exited_at",
        "last_seen_at",
    ):
        op.create_index(
            f"ix_occupancy_sessions_{column}",
            "occupancy_sessions",
            [column],
        )
    op.create_index(
        "uq_occupancy_active_journey",
        "occupancy_sessions",
        ["journey_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('ACTIVE', 'TEMPORARILY_LOST', 'STALE', "
            "'NEED_REVIEW')"
        ),
    )


def downgrade() -> None:
    op.drop_table("occupancy_sessions")
    op.drop_table("occupancy_facts")
    bind = op.get_bind()
    postgresql.ENUM(name="occupancy_fact_type").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(name="occupancy_session_state").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(name="occupancy_subject_type").drop(
        bind, checkfirst=True
    )
