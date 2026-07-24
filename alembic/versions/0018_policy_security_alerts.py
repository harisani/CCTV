"""policy rules, evaluations, and security alerts

Revision ID: 0018_policy_security_alerts
Revises: 0017_occupancy_engine
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_policy_security_alerts"
down_revision: str | None = "0017_occupancy_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "ZONE_AUTHORIZATION", "DIVISION_PERMISSION", "PPE_COLOR",
        "PPE_COMPLETENESS", "RESTRICTED_ZONE", "UNKNOWN_PERSON",
        "UNRESOLVED_PERSON", "CAMERA_OFFLINE", "PROCESSING_DELAY",
        "IDENTITY_CONFLICT", name="policy_rule_type",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "UNKNOWN_ENTER", "UNKNOWN_ACTIVE", "UNRESOLVED_IDENTITY",
        "UNAUTHORIZED_ZONE_ENTRY", "PPE_MISMATCH", "PPE_INCOMPLETE",
        "IDENTITY_CONFLICT", "IMPOSSIBLE_TRAVEL", "CAMERA_OFFLINE",
        "PROCESSING_BACKLOG", "CAPTURE_FAILURE", "DUPLICATE_JOURNEY",
        "MANUAL_CORRECTION", name="security_alert_type",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "LOW", "MEDIUM", "HIGH", "CRITICAL",
        name="security_alert_severity",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED",
        name="security_alert_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "COMPLETED", "INCONCLUSIVE", "FAILED",
        name="policy_evaluation_status",
    ).create(bind, checkfirst=True)

    op.create_table(
        "subject_policy_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), nullable=True, unique=True),
        sa.Column("external_subject_key", sa.String(160), nullable=True, unique=True),
        sa.Column("employee_key", sa.String(100), nullable=True),
        sa.Column("department_code", sa.String(100), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("profile_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "person_id IS NOT NULL OR external_subject_key IS NOT NULL",
            name="ck_subject_policy_profile_subject",
        ),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
    )
    for column in ("person_id", "external_subject_key", "employee_key", "department_code", "active"):
        op.create_index(f"ix_subject_policy_profiles_{column}", "subject_policy_profiles", [column])

    op.create_table(
        "policy_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("rule_type", _enum("policy_rule_type"), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("severity", _enum("security_alert_severity"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    for column in ("name", "rule_type", "zone_id", "priority", "enabled"):
        op.create_index(f"ix_policy_rules_{column}", "policy_rules", [column])

    op.create_table(
        "security_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("deduplication_key", sa.String(240), nullable=False, unique=True),
        sa.Column("alert_type", _enum("security_alert_type"), nullable=False),
        sa.Column("severity", _enum("security_alert_severity"), nullable=False),
        sa.Column("status", _enum("security_alert_status"), nullable=False),
        sa.Column("policy_rule_id", sa.Uuid(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("journey_id", sa.Uuid(), nullable=True),
        sa.Column("occupancy_session_id", sa.Uuid(), nullable=True),
        sa.Column("capture_event_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("external_subject_key", sa.String(160), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["policy_rule_id"], ["policy_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journey_id"], ["global_journeys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["occupancy_session_id"], ["occupancy_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["capture_event_id"], ["capture_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    for column in (
        "deduplication_key", "alert_type", "severity", "status",
        "policy_rule_id", "zone_id", "camera_id", "journey_id",
        "occupancy_session_id", "capture_event_id", "person_id",
        "external_subject_key", "occurred_at", "created_at",
        "reviewed_by_user_id",
    ):
        op.create_index(f"ix_security_alerts_{column}", "security_alerts", [column])

    op.create_table(
        "policy_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("occupancy_fact_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("policy_evaluation_status"), nullable=False),
        sa.Column("evaluated_rule_count", sa.Integer(), nullable=False),
        sa.Column("alert_count", sa.Integer(), nullable=False),
        sa.Column("decisions", postgresql.JSONB(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["occupancy_fact_id"], ["occupancy_facts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_event_id"], ["capture_events.id"], ondelete="RESTRICT"),
    )
    for column in ("idempotency_key", "occupancy_fact_id", "capture_event_id", "status", "evaluated_at"):
        op.create_index(f"ix_policy_evaluations_{column}", "policy_evaluations", [column])


def downgrade() -> None:
    op.drop_table("policy_evaluations")
    op.drop_table("security_alerts")
    op.drop_table("policy_rules")
    op.drop_table("subject_policy_profiles")
    bind = op.get_bind()
    for name in (
        "policy_evaluation_status", "security_alert_status",
        "security_alert_severity", "security_alert_type", "policy_rule_type",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
