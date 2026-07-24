"""face candidates, biometric templates, and identity decisions

Revision ID: 0014_biometric_identity
Revises: 0013_local_zone_transitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0014_biometric_identity"
down_revision: str | None = "0013_local_zone_transitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    biometric_modality = postgresql.ENUM(
        "FACE",
        "PERIOCULAR",
        name="biometric_modality",
    )
    identity_decision = postgresql.ENUM(
        "CONFIRMED",
        "PROBABLE",
        "UNRESOLVED",
        "UNKNOWN",
        "CONFLICT",
        name="identity_decision",
    )
    identity_review_status = postgresql.ENUM(
        "NOT_REQUIRED",
        "PENDING",
        "APPROVED",
        "REJECTED",
        name="identity_review_status",
    )
    bind = op.get_bind()
    biometric_modality.create(bind, checkfirst=True)
    identity_decision.create(bind, checkfirst=True)
    identity_review_status.create(bind, checkfirst=True)
    modality_column = postgresql.ENUM(
        "FACE",
        "PERIOCULAR",
        name="biometric_modality",
        create_type=False,
    )
    decision_column = postgresql.ENUM(
        "CONFIRMED",
        "PROBABLE",
        "UNRESOLVED",
        "UNKNOWN",
        "CONFLICT",
        name="identity_decision",
        create_type=False,
    )
    review_column = postgresql.ENUM(
        "NOT_REQUIRED",
        "PENDING",
        "APPROVED",
        "REJECTED",
        name="identity_review_status",
        create_type=False,
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("task", sa.String(length=100), nullable=False),
        sa.Column("runtime", sa.String(length=80), nullable=False),
        sa.Column(
            "artifact_checksum_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "native_embedding_dimension", sa.Integer(), nullable=True
        ),
        sa.Column(
            "thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_key",
            "version",
            name="uq_model_version_key_version",
        ),
    )
    op.create_index(
        "ix_model_versions_model_key", "model_versions", ["model_key"]
    )
    op.create_index(
        "ix_model_versions_task", "model_versions", ["task"]
    )
    op.create_index(
        "ix_model_versions_enabled", "model_versions", ["enabled"]
    )

    op.create_table(
        "face_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("face_asset_id", sa.Uuid(), nullable=True),
        sa.Column("periocular_asset_id", sa.Uuid(), nullable=True),
        sa.Column("detector_model_version_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column(
            "bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "landmarks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
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
        sa.Column(
            "rejection_reason", sa.String(length=160), nullable=True
        ),
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
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["detector_model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["face_asset_id"],
            ["evidence_assets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["periocular_asset_id"],
            ["evidence_assets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capture_event_id",
            "sequence_index",
            name="uq_face_candidate_capture_sequence",
        ),
    )
    for column in (
        "capture_event_id",
        "face_asset_id",
        "periocular_asset_id",
        "detector_model_version_id",
        "quality_score",
        "selected",
        "captured_at",
    ):
        op.create_index(
            f"ix_face_candidates_{column}",
            "face_candidates",
            [column],
        )

    op.create_table(
        "biometric_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "external_subject_key", sa.String(length=160), nullable=True
        ),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("modality", modality_column, nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("native_dimension", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column(
            "template_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "enrolled_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "person_id IS NOT NULL OR external_subject_key IS NOT NULL",
            name="ck_biometric_template_subject",
        ),
        sa.CheckConstraint(
            "native_dimension BETWEEN 1 AND 512",
            name="ck_biometric_template_native_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["evidence_assets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "person_id",
        "external_subject_key",
        "source_asset_id",
        "model_version_id",
        "modality",
        "quality_score",
        "active",
        "enrolled_at",
        "expires_at",
    ):
        op.create_index(
            f"ix_biometric_templates_{column}",
            "biometric_templates",
            [column],
        )

    op.create_table(
        "identity_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("face_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("matched_template_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "candidate_external_subject_key",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("modality", modality_column, nullable=False),
        sa.Column("decision", decision_column, nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("second_best_similarity", sa.Float(), nullable=True),
        sa.Column(
            "reasoning_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("review_status", review_column, nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["candidate_person_id"],
            ["persons.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"],
            ["capture_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["face_candidate_id"],
            ["face_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["matched_template_id"],
            ["biometric_templates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "capture_event_id",
            "model_version_id",
            name="uq_identity_match_capture_model",
        ),
    )
    for column in (
        "capture_event_id",
        "face_candidate_id",
        "matched_template_id",
        "candidate_person_id",
        "candidate_external_subject_key",
        "model_version_id",
        "modality",
        "decision",
        "confidence_score",
        "review_status",
        "matched_at",
    ):
        op.create_index(
            f"ix_identity_matches_{column}",
            "identity_matches",
            [column],
        )


def downgrade() -> None:
    op.drop_table("identity_matches")
    op.drop_table("biometric_templates")
    op.drop_table("face_candidates")
    op.drop_table("model_versions")
    postgresql.ENUM(
        name="identity_review_status"
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="identity_decision").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="biometric_modality").drop(
        op.get_bind(), checkfirst=True
    )
