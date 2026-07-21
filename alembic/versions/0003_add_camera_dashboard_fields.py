"""add camera grouping and health fields

Revision ID: 0003_camera_dashboard
Revises: 0002_add_person_display_name
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_camera_dashboard"
down_revision = "0002_add_person_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("location", sa.String(length=150), nullable=True))
    op.add_column("cameras", sa.Column("building", sa.String(length=100), nullable=True))
    op.add_column("cameras", sa.Column("floor", sa.String(length=50), nullable=True))
    op.add_column("cameras", sa.Column("zone", sa.String(length=100), nullable=True))
    op.add_column("cameras", sa.Column("status", sa.String(length=20), nullable=False, server_default="OFFLINE"))
    op.add_column("cameras", sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cameras", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("cameras", sa.Column("worker_id", sa.String(length=100), nullable=True))
    op.add_column("cameras", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    for column in ("location", "building", "floor", "zone", "status", "worker_id", "display_order"):
        op.create_index(f"ix_cameras_{column}", "cameras", [column])


def downgrade() -> None:
    for column in reversed(("location", "building", "floor", "zone", "status", "worker_id", "display_order")):
        op.drop_index(f"ix_cameras_{column}", table_name="cameras")
    for column in reversed(
        ("location", "building", "floor", "zone", "status", "last_frame_at", "last_error", "worker_id", "display_order")
    ):
        op.drop_column("cameras", column)
