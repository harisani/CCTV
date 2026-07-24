"""global journeys and multi-camera correlation decisions

Revision ID: 0016_global_journeys
Revises: 0015_body_reid_ppe
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_global_journeys"
down_revision: str | None = "0015_body_reid_ppe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    journey_status = postgresql.ENUM(
        "ACTIVE",
        "NEED_REVIEW",
        "CLOSED",
        name="journey_status",
    )
    journey_event_type = postgresql.ENUM(
        "OBSERVATION",
        "ZONE_TRANSITION",
        name="journey_event_type",
    )
    journey_decision = postgresql.ENUM(
        "CREATED",
        "MATCHED",
        "AMBIGUOUS",
        "IMPOSSIBLE_TRAVEL",
        name="journey_correlation_decision",
    )
    bind = op.get_bind()
    journey_status.create(bind, checkfirst=True)
    journey_event_type.create(bind, checkfirst=True)
    journey_decision.create(bind, checkfirst=True)

    op.create_table(
        "global_journeys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journey_key", sa.String(length=40), nullable=False),
        sa.Column("identity_person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "identity_external_subject_key",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "identity_decision",
            _enum("identity_decision"),
            nullable=False,
        ),
        sa.Column("identity_confidence", sa.Float(), nullable=False),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("current_zone_id", sa.Uuid(), nullable=True),
        sa.Column("last_camera_id", sa.Uuid(), nullable=True),
        sa.Column("last_event_id", sa.Uuid(), nullable=True),
        sa.Column("status", _enum("journey_status"), nullable=False),
        sa.Column(
            "review_status",
            _enum("identity_review_status"),
            nullable=False,
        ),
        sa.Column(
            "event_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "version",
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
            "last_seen_at >= first_seen_at",
            name="ck_global_journey_time_order",
        ),
        sa.CheckConstraint(
            "identity_confidence BETWEEN 0 AND 1",
            name="ck_global_journey_identity_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["current_zone_id"], ["zones.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["identity_person_id"], ["persons.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_camera_id"], ["cameras.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journey_key"),
        sa.UniqueConstraint("last_event_id"),
    )
    for column in (
        "journey_key",
        "identity_person_id",
        "identity_external_subject_key",
        "identity_decision",
        "identity_confidence",
        "first_seen_at",
        "last_seen_at",
        "current_zone_id",
        "last_camera_id",
        "status",
        "review_status",
    ):
        op.create_index(
            f"ix_global_journeys_{column}",
            "global_journeys",
            [column],
        )

    op.create_table(
        "journey_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("tracking_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("origin_zone_id", sa.Uuid(), nullable=True),
        sa.Column("destination_zone_id", sa.Uuid(), nullable=True),
        sa.Column("current_zone_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event_type",
            _enum("journey_event_type"),
            nullable=False,
        ),
        sa.Column("identity_person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "identity_external_subject_key",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "identity_decision",
            _enum("identity_decision"),
            nullable=False,
        ),
        sa.Column("identity_confidence", sa.Float(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "evidence_metadata",
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
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["destination_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["identity_person_id"], ["persons.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["global_journeys.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["origin_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tracking_id"], ["trackings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capture_event_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "idempotency_key",
        "journey_id",
        "capture_event_id",
        "tracking_id",
        "camera_id",
        "origin_zone_id",
        "destination_zone_id",
        "current_zone_id",
        "event_type",
        "identity_person_id",
        "identity_external_subject_key",
        "identity_decision",
        "occurred_at",
    ):
        op.create_index(
            f"ix_journey_events_{column}",
            "journey_events",
            [column],
        )
    op.create_foreign_key(
        "fk_global_journeys_last_event",
        "global_journeys",
        "journey_events",
        ["last_event_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "journey_correlations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("journey_event_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_journey_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "decision",
            _enum("journey_correlation_decision"),
            nullable=False,
        ),
        sa.Column("correlation_score", sa.Float(), nullable=False),
        sa.Column("second_best_score", sa.Float(), nullable=True),
        sa.Column("identity_score", sa.Float(), nullable=False),
        sa.Column("topology_score", sa.Float(), nullable=False),
        sa.Column("time_score", sa.Float(), nullable=False),
        sa.Column("appearance_score", sa.Float(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column(
            "impossible_travel",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "reasoning_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "correlated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "correlation_score BETWEEN 0 AND 1",
            name="ck_journey_correlation_score",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_journey_event_id"],
            ["journey_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["journey_event_id"],
            ["journey_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["global_journeys.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capture_event_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("journey_event_id"),
    )
    for column in (
        "idempotency_key",
        "capture_event_id",
        "journey_id",
        "journey_event_id",
        "anchor_journey_event_id",
        "decision",
        "correlation_score",
        "impossible_travel",
        "correlated_at",
    ):
        op.create_index(
            f"ix_journey_correlations_{column}",
            "journey_correlations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("journey_correlations")
    op.drop_constraint(
        "fk_global_journeys_last_event",
        "global_journeys",
        type_="foreignkey",
    )
    op.drop_table("journey_events")
    op.drop_table("global_journeys")
    bind = op.get_bind()
    postgresql.ENUM(name="journey_correlation_decision").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(name="journey_event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="journey_status").drop(bind, checkfirst=True)
