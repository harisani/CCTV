"""local tracking observations and zone transition events

Revision ID: 0013_local_zone_transitions
Revises: 0012_async_processing_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_local_zone_transitions"
down_revision: str | None = "0012_async_processing_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trackings",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trackings",
        sa.Column(
            "last_bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "trackings",
        sa.Column("detector_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "trackings",
        sa.Column("direction", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "trackings",
        sa.Column("detector_model", sa.String(length=120), nullable=True),
    )
    op.execute(
        """
        UPDATE trackings
        SET last_seen_at = COALESCE(ended_at, started_at, now())
        WHERE last_seen_at IS NULL
        """
    )
    op.alter_column("trackings", "last_seen_at", nullable=False)
    op.create_index(
        "ix_trackings_last_seen_at",
        "trackings",
        ["last_seen_at"],
    )

    zone_event_type = sa.Enum(
        "ZONE_ENTER",
        "ZONE_EXIT",
        name="zone_event_type",
    )
    op.create_table(
        "zone_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("crossing_event_id", sa.Uuid(), nullable=True),
        sa.Column("tracking_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("virtual_line_id", sa.Uuid(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column("origin_zone_id", sa.Uuid(), nullable=True),
        sa.Column("destination_zone_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", zone_event_type, nullable=False),
        sa.Column("local_track_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column(
            "centroid",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
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
            ["crossing_event_id"], ["events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["destination_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["origin_zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tracking_id"], ["trackings.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["virtual_line_id"], ["virtual_lines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zones.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "transition_id",
            "event_type",
            "zone_id",
            name="uq_zone_event_transition_type_zone",
        ),
    )
    for column in (
        "idempotency_key",
        "transition_id",
        "crossing_event_id",
        "tracking_id",
        "camera_id",
        "virtual_line_id",
        "zone_id",
        "origin_zone_id",
        "destination_zone_id",
        "event_type",
        "local_track_id",
        "direction",
        "occurred_at",
    ):
        op.create_index(
            f"ix_zone_events_{column}",
            "zone_events",
            [column],
        )
    op.create_index(
        "ix_zone_events_zone_occurred",
        "zone_events",
        ["zone_id", "occurred_at"],
    )
    op.create_index(
        "ix_zone_events_camera_occurred",
        "zone_events",
        ["camera_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("zone_events")
    sa.Enum(name="zone_event_type").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_trackings_last_seen_at", table_name="trackings")
    op.drop_column("trackings", "detector_model")
    op.drop_column("trackings", "direction")
    op.drop_column("trackings", "detector_confidence")
    op.drop_column("trackings", "last_bbox")
    op.drop_column("trackings", "last_seen_at")
