"""add RBAC users and audit logs

Revision ID: 0004_users_rbac
Revises: 0003_camera_dashboard
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_users_rbac"
down_revision = "0003_camera_dashboard"
branch_labels = None
depends_on = None

user_role = sa.Enum("SUPER_ADMIN", "ADMIN", "SUPERVISOR", "OPERATOR", "AUDITOR", name="user_role")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    for column in ("username", "role", "is_active"):
        op.create_index(f"ix_users_{column}", "users", [column])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("actor_user_id", "action", "resource_type", "resource_id", "created_at"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])


def downgrade() -> None:
    for column in reversed(("actor_user_id", "action", "resource_type", "resource_id", "created_at")):
        op.drop_index(f"ix_audit_logs_{column}", table_name="audit_logs")
    op.drop_table("audit_logs")
    for column in reversed(("username", "role", "is_active")):
        op.drop_index(f"ix_users_{column}", table_name="users")
    op.drop_table("users")
    user_role.drop(op.get_bind(), checkfirst=True)
