"""durable presence sessions and uncertain occupancy

Revision ID: 0009_presence_sessions
Revises: 0008_production_reid
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_presence_sessions"
down_revision: str | None = "0008_production_reid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    presence_status = sa.Enum("ACTIVE", "UNCERTAIN", "CLOSED", name="presence_status")
    op.create_table(
        "presence_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("entry_tracking_id", sa.Uuid(), nullable=True),
        sa.Column("exit_tracking_id", sa.Uuid(), nullable=True),
        sa.Column("entry_event_id", sa.Uuid(), nullable=True),
        sa.Column("exit_event_id", sa.Uuid(), nullable=True),
        sa.Column("status", presence_status, nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uncertain_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entry_tracking_id"], ["trackings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["exit_tracking_id"], ["trackings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entry_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["exit_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_event_id"),
        sa.UniqueConstraint("exit_event_id"),
    )
    for column in (
        "person_id",
        "camera_id",
        "entry_tracking_id",
        "exit_tracking_id",
        "entry_event_id",
        "exit_event_id",
        "status",
        "entered_at",
        "exited_at",
        "uncertain_since",
        "last_confirmed_at",
    ):
        op.create_index(f"ix_presence_sessions_{column}", "presence_sessions", [column])
    op.execute(
        "CREATE UNIQUE INDEX uq_presence_sessions_open_person "
        "ON presence_sessions (person_id) "
        "WHERE person_id IS NOT NULL AND status IN ('ACTIVE', 'UNCERTAIN')"
    )

    # Preserve the latest known state for installations that already have events.
    op.execute(
        """
        WITH latest AS (
            SELECT e.id AS event_id, e.event_type, e.occurred_at,
                   t.id AS tracking_id, t.person_id, t.camera_id,
                   row_number() OVER (
                       PARTITION BY t.person_id ORDER BY e.occurred_at DESC, e.id DESC
                   ) AS rank
            FROM events e
            JOIN trackings t ON t.id = e.tracking_id
            WHERE t.person_id IS NOT NULL
        )
        INSERT INTO presence_sessions (
            id, person_id, camera_id, entry_tracking_id, entry_event_id,
            status, entered_at, last_confirmed_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), person_id, camera_id, tracking_id, event_id,
               'ACTIVE', occurred_at, occurred_at, now(), now()
        FROM latest
        WHERE rank = 1 AND event_type = 'ENTER'
        """
    )


def downgrade() -> None:
    op.drop_table("presence_sessions")
    sa.Enum(name="presence_status").drop(op.get_bind(), checkfirst=True)
