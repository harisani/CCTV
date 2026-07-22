"""production person ReID templates and identity lineage

Revision ID: 0008_production_reid
Revises: 0007_camera_crossing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0008_production_reid"
down_revision: str | None = "0007_camera_crossing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "persons", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "persons", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("persons", sa.Column("merged_into_person_id", sa.Uuid(), nullable=True))
    op.add_column(
        "persons", sa.Column("identity_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_foreign_key(
        "fk_persons_merged_into_person_id",
        "persons",
        "persons",
        ["merged_into_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in ("is_active", "needs_review", "merged_into_person_id"):
        op.create_index(f"ix_persons_{column}", "persons", [column])

    op.create_table(
        "person_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tracking_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("match_similarity", sa.Float(), nullable=True),
        sa.Column("match_decision", sa.String(length=30), nullable=False),
        sa.Column("matched_embedding_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_id"], ["trackings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["matched_embedding_id"], ["person_embeddings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "person_id", "tracking_id", "camera_id", "model_name", "quality_score",
        "match_decision", "captured_at", "expires_at", "is_active",
    ):
        op.create_index(f"ix_person_embeddings_{column}", "person_embeddings", [column])
    op.execute(
        "CREATE INDEX ix_person_embeddings_vector_hnsw "
        "ON person_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WHERE is_active IS TRUE"
    )
    op.execute(
        """
        INSERT INTO person_embeddings (
            id, person_id, model_name, dimension, embedding, quality_score,
            match_decision, captured_at, match_count, is_active, created_at
        )
        SELECT gen_random_uuid(), id,
               COALESCE(reid_embedding->>'model', 'osnet_x1_0'), 512,
               ((reid_embedding->'vector')::text)::vector(512), 1.0,
               'LEGACY_IMPORT', first_seen_at, 0, TRUE, created_at
        FROM persons
        WHERE reid_embedding IS NOT NULL
          AND json_typeof(reid_embedding->'vector') = 'array'
          AND json_array_length(reid_embedding->'vector') = 512
        """
    )
    op.execute("UPDATE persons SET reid_embedding = NULL WHERE reid_embedding IS NOT NULL")


def downgrade() -> None:
    op.execute(
        """
        UPDATE persons AS p
        SET reid_embedding = json_build_object(
            'model', e.model_name,
            'vector', (e.embedding::text)::json
        )
        FROM person_embeddings AS e
        WHERE e.person_id = p.id
          AND e.id = (
              SELECT selected.id FROM person_embeddings AS selected
              WHERE selected.person_id = p.id
              ORDER BY selected.quality_score DESC, selected.created_at DESC
              LIMIT 1
          )
        """
    )
    op.drop_table("person_embeddings")
    for column in ("merged_into_person_id", "needs_review", "is_active"):
        op.drop_index(f"ix_persons_{column}", table_name="persons")
    op.drop_constraint("fk_persons_merged_into_person_id", "persons", type_="foreignkey")
    for column in ("identity_version", "merged_into_person_id", "needs_review", "is_active"):
        op.drop_column("persons", column)
