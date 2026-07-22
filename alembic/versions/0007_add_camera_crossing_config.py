"""add per-camera crossing geometry

Revision ID: 0007_camera_crossing
Revises: 0006_disaster_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_camera_crossing"
down_revision: str | None = "0006_disaster_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "crossing_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "crossing_config")
