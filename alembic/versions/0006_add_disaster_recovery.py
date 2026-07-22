"""Add encrypted full disaster-recovery archive catalogue.

Revision ID: 0006_disaster_recovery
Revises: 0005_backup_archives
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_disaster_recovery"
down_revision: str | None = "0005_backup_archives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status_enum = sa.Enum(
        "CREATING", "READY", "RESTORING", "RESTORED", "FAILED",
        name="disaster_recovery_status",
    )
    op.create_table(
        "disaster_recovery_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("schedule_key", sa.String(length=40), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("offsite_path", sa.Text(), nullable=True),
        sa.Column("offsite_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("restore_database", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_key"),
        sa.UniqueConstraint("file_path"),
        sa.UniqueConstraint("checksum_sha256"),
    )
    for column in ("status", "checksum_sha256", "created_by_user_id", "created_at"):
        op.create_index(
            f"ix_disaster_recovery_archives_{column}",
            "disaster_recovery_archives",
            [column],
        )


def downgrade() -> None:
    op.drop_table("disaster_recovery_archives")
    sa.Enum(name="disaster_recovery_status").drop(op.get_bind(), checkfirst=True)
