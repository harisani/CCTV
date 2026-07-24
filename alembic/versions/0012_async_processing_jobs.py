"""durable asynchronous AI processing queue

Revision ID: 0012_async_processing_jobs
Revises: 0011_capture_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_async_processing_jobs"
down_revision: str | None = "0011_capture_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    job_status = sa.Enum(
        "QUEUED",
        "PROCESSING",
        "RETRYING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        name="ai_job_status",
    )
    job_type = sa.Enum(
        "CAPTURE_INGESTION",
        "PERSON_DETECTION",
        "IDENTITY_CORRELATION",
        "JOURNEY_CORRELATION",
        "OCCUPANCY_UPDATE",
        "POLICY_EVALUATION",
        name="ai_job_type",
    )
    processing_priority = postgresql.ENUM(
        "LOW",
        "NORMAL",
        "HIGH",
        name="processing_priority",
        create_type=False,
    )

    op.add_column(
        "capture_events",
        sa.Column(
            "dashboard_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "capture_events",
        sa.Column("processing_latency_ms", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "capture_events",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "capture_events",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_capture_event_processing_latency",
        "capture_events",
        "processing_latency_ms IS NULL OR processing_latency_ms >= 0",
    )
    op.create_check_constraint(
        "ck_capture_event_retry_count",
        "capture_events",
        "retry_count >= 0",
    )

    op.create_table(
        "ai_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column(
            "status",
            job_status,
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column(
            "priority",
            processing_priority,
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_heartbeat_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_ai_job_attempt_count"
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 100",
            name="ck_ai_job_max_attempts",
        ),
        sa.CheckConstraint(
            "attempt_count <= max_attempts",
            name="ck_ai_job_attempt_limit",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"], ["capture_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "capture_event_id",
        "job_type",
        "status",
        "priority",
        "available_at",
        "locked_by",
        "lock_expires_at",
        "completed_at",
        "last_error_code",
        "created_at",
    ):
        op.create_index(
            f"ix_ai_processing_jobs_{column}",
            "ai_processing_jobs",
            [column],
        )
    op.create_index(
        "ix_ai_processing_jobs_claim",
        "ai_processing_jobs",
        ["status", "available_at", "priority", "created_at"],
    )
    op.create_index(
        "ix_ai_processing_jobs_expired_lease",
        "ai_processing_jobs",
        ["status", "lock_expires_at"],
    )

    op.execute(
        """
        INSERT INTO ai_processing_jobs (
            id,
            capture_event_id,
            job_type,
            status,
            priority,
            idempotency_key,
            payload,
            attempt_count,
            max_attempts,
            available_at,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            capture.id,
            'CAPTURE_INGESTION'::ai_job_type,
            'QUEUED'::ai_job_status,
            COALESCE(zone.processing_priority, 'NORMAL'::processing_priority),
            'capture-ingestion:' || capture.id::text,
            jsonb_build_object(
                'capture_event_id', capture.id,
                'legacy_backfill', true
            ),
            0,
            5,
            now(),
            now(),
            now()
        FROM capture_events AS capture
        LEFT JOIN zones AS zone ON zone.id = capture.zone_id
        WHERE capture.status = 'CAPTURED'::capture_event_status
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE capture_events AS capture
        SET
            status = 'QUEUED'::capture_event_status,
            updated_at = now()
        WHERE EXISTS (
            SELECT 1
            FROM ai_processing_jobs AS job
            WHERE job.capture_event_id = capture.id
              AND job.status = 'QUEUED'::ai_job_status
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE capture_events AS capture
        SET
            status = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM evidence_assets AS asset
                    WHERE asset.capture_event_id = capture.id
                      AND asset.deleted_at IS NULL
                )
                    THEN 'CAPTURED'::capture_event_status
                ELSE 'FAILED'::capture_event_status
            END,
            processing_started_at = NULL,
            processed_at = NULL,
            updated_at = now()
        WHERE EXISTS (
            SELECT 1
            FROM ai_processing_jobs AS job
            WHERE job.capture_event_id = capture.id
        )
        """
    )
    op.drop_table("ai_processing_jobs")
    sa.Enum(name="ai_job_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ai_job_status").drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "ck_capture_event_retry_count",
        "capture_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_capture_event_processing_latency",
        "capture_events",
        type_="check",
    )
    op.drop_column("capture_events", "failure_reason")
    op.drop_column("capture_events", "retry_count")
    op.drop_column("capture_events", "processing_latency_ms")
    op.drop_column("capture_events", "dashboard_updated_at")
