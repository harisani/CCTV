"""add optional person display name

Revision ID: 0002_add_person_display_name
Revises: 0001_initial_schema
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_person_display_name"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("display_name", sa.String(length=100), nullable=True))
    op.create_index("ix_persons_display_name", "persons", ["display_name"])


def downgrade() -> None:
    op.drop_index("ix_persons_display_name", table_name="persons")
    op.drop_column("persons", "display_name")
