"""Add isolated backup archive catalogue.

Revision ID: 0005_backup_archives
Revises: 0004_users_rbac
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_backup_archives"
down_revision: str | None = "0004_users_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("AUTOMATIC", "MANUAL", "IMPORT", name="backup_source"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("CREATING", "READY", "FAILED", name="backup_status"),
            nullable=False,
        ),
        sa.Column("backup_date", sa.Date(), nullable=False),
        sa.Column("schedule_key", sa.String(length=40), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("record_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
    for column in (
        "source",
        "status",
        "backup_date",
        "checksum_sha256",
        "created_by_user_id",
        "created_at",
    ):
        op.create_index(f"ix_backup_archives_{column}", "backup_archives", [column])


def downgrade() -> None:
    op.drop_table("backup_archives")
    sa.Enum(name="backup_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="backup_source").drop(op.get_bind(), checkfirst=True)
