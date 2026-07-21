"""create initial CCTV persistence schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

event_type = sa.Enum("ENTER", "EXIT", name="event_type")


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rtsp_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("name"),
    )
    op.create_index("ix_cameras_name", "cameras", ["name"])
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("reid_key", sa.String(128), nullable=True),
        sa.Column("reid_embedding", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("reid_key"),
    )
    op.create_index("ix_persons_reid_key", "persons", ["reid_key"])
    op.create_table(
        "trackings",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True), sa.Column("byte_track_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_centroid", sa.JSON(), nullable=True), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "byte_track_id", "started_at", name="uq_tracking_camera_track_started"),
    )
    for name, column in (("ix_trackings_camera_id", "camera_id"), ("ix_trackings_person_id", "person_id"), ("ix_trackings_byte_track_id", "byte_track_id"), ("ix_trackings_is_active", "is_active")):
        op.create_index(name, "trackings", [column])
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("tracking_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", event_type, nullable=False), sa.Column("line_id", sa.String(100), nullable=False),
        sa.Column("centroid", sa.JSON(), nullable=False), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tracking_id"], ["trackings.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    for name, column in (("ix_events_tracking_id", "tracking_id"), ("ix_events_event_type", "event_type"), ("ix_events_line_id", "line_id"), ("ix_events_occurred_at", "occurred_at")):
        op.create_index(name, "events", [column])
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False), sa.Column("metadata_path", sa.Text(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False), sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_snapshots_event_id", "snapshots", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshots_event_id", table_name="snapshots")
    op.drop_table("snapshots")
    for name in ("ix_events_occurred_at", "ix_events_line_id", "ix_events_event_type", "ix_events_tracking_id"):
        op.drop_index(name, table_name="events")
    op.drop_table("events")
    for name in ("ix_trackings_is_active", "ix_trackings_byte_track_id", "ix_trackings_person_id", "ix_trackings_camera_id"):
        op.drop_index(name, table_name="trackings")
    op.drop_table("trackings")
    op.drop_index("ix_persons_reid_key", table_name="persons")
    op.drop_table("persons")
    op.drop_index("ix_cameras_name", table_name="cameras")
    op.drop_table("cameras")
