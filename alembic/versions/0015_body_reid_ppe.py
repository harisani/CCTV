"""full-body candidates, body ReID, and PPE observations

Revision ID: 0015_body_reid_ppe
Revises: 0014_biometric_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0015_body_reid_ppe"
down_revision: str | None = "0014_biometric_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE biometric_modality ADD VALUE IF NOT EXISTS 'BODY'"
    )
    op.execute(
        "ALTER TYPE ai_job_type ADD VALUE IF NOT EXISTS "
        "'BODY_REIDENTIFICATION'"
    )
    op.execute(
        "ALTER TYPE ai_job_type ADD VALUE IF NOT EXISTS 'PPE_ANALYSIS'"
    )
    ppe_status = postgresql.ENUM(
        "COMPLETED",
        "PARTIAL",
        "UNRESOLVED",
        "MODEL_UNAVAILABLE",
        "FAILED",
        name="ppe_analysis_status",
    )
    ppe_status.create(op.get_bind(), checkfirst=True)
    ppe_status_column = postgresql.ENUM(
        "COMPLETED",
        "PARTIAL",
        "UNRESOLVED",
        "MODEL_UNAVAILABLE",
        "FAILED",
        name="ppe_analysis_status",
        create_type=False,
    )

    op.create_table(
        "body_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("body_asset_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column(
            "bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("detector_confidence", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column(
            "quality_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "selected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("rejection_reason", sa.String(length=160), nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["body_asset_id"],
            ["evidence_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capture_event_id",
            "sequence_index",
            name="uq_body_candidate_capture_sequence",
        ),
    )
    for column in (
        "capture_event_id",
        "body_asset_id",
        "quality_score",
        "selected",
        "captured_at",
    ):
        op.create_index(
            f"ix_body_candidates_{column}",
            "body_candidates",
            [column],
        )

    op.create_table(
        "body_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("body_candidate_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["body_candidate_id"],
            ["body_candidates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "body_candidate_id",
            "model_version_id",
            name="uq_body_embedding_candidate_model",
        ),
    )
    for column in (
        "body_candidate_id",
        "person_id",
        "model_version_id",
        "quality_score",
        "source",
        "active",
        "captured_at",
        "expires_at",
    ):
        op.create_index(
            f"ix_body_embeddings_{column}",
            "body_embeddings",
            [column],
        )
    op.create_index(
        "ix_body_embeddings_vector_hnsw",
        "body_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.add_column(
        "identity_matches",
        sa.Column("body_candidate_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "identity_matches",
        sa.Column("matched_body_embedding_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_identity_matches_body_candidate",
        "identity_matches",
        "body_candidates",
        ["body_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_identity_matches_body_embedding",
        "identity_matches",
        "body_embeddings",
        ["matched_body_embedding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_identity_matches_body_candidate_id",
        "identity_matches",
        ["body_candidate_id"],
    )
    op.create_index(
        "ix_identity_matches_matched_body_embedding_id",
        "identity_matches",
        ["matched_body_embedding_id"],
    )

    op.create_table(
        "ppe_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("body_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", ppe_status_column, nullable=False),
        sa.Column(
            "detections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "observed_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "color_observation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column(
            "reasoning_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "analyzed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["body_candidate_id"],
            ["body_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capture_event_id",
            name="uq_ppe_analysis_capture",
        ),
    )
    for column in (
        "capture_event_id",
        "body_candidate_id",
        "model_version_id",
        "status",
        "confidence_score",
        "needs_review",
        "analyzed_at",
    ):
        op.create_index(
            f"ix_ppe_analyses_{column}",
            "ppe_analyses",
            [column],
        )


def downgrade() -> None:
    op.drop_table("ppe_analyses")
    op.drop_index(
        "ix_identity_matches_matched_body_embedding_id",
        table_name="identity_matches",
    )
    op.drop_index(
        "ix_identity_matches_body_candidate_id",
        table_name="identity_matches",
    )
    op.drop_constraint(
        "fk_identity_matches_body_embedding",
        "identity_matches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_identity_matches_body_candidate",
        "identity_matches",
        type_="foreignkey",
    )
    op.drop_column("identity_matches", "matched_body_embedding_id")
    op.drop_column("identity_matches", "body_candidate_id")
    op.drop_table("body_embeddings")
    op.drop_table("body_candidates")
    postgresql.ENUM(name="ppe_analysis_status").drop(
        op.get_bind(), checkfirst=True
    )
    # PostgreSQL enum values are intentionally retained. Recreating shared
    # enums would require rewriting live ai_processing_jobs/identity_matches.
