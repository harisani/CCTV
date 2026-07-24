"""capture events and immutable evidence assets

Revision ID: 0011_capture_evidence
Revises: 0010_factory_topology
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_capture_evidence"
down_revision: str | None = "0010_factory_topology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    capture_status = sa.Enum(
        "CAPTURED",
        "QUEUED",
        "PROCESSING",
        "COMPLETED",
        "NEED_REVIEW",
        "FAILED",
        "RETRYING",
        "CANCELLED",
        name="capture_event_status",
    )
    asset_type = sa.Enum(
        "ORIGINAL_SNAPSHOT",
        "ANNOTATED_SNAPSHOT",
        "FACE_CROP",
        "PERIOCULAR_CROP",
        "FULL_BODY",
        "THUMBNAIL",
        "VIDEO_CLIP",
        "METADATA_JSON",
        name="evidence_asset_type",
    )
    integrity_status = sa.Enum(
        "VERIFIED",
        "UNVERIFIED",
        "MISSING",
        "CORRUPT",
        name="evidence_integrity_status",
    )

    op.create_table(
        "capture_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("virtual_line_id", sa.Uuid(), nullable=True),
        sa.Column("tracking_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            capture_status,
            nullable=False,
            server_default="CAPTURED",
        ),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column(
            "bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "centroid", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "capture_quality",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "capture_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "processing_started_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_capture_event_attempt_count"
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zones.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["virtual_line_id"], ["virtual_lines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tracking_id"], ["trackings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("source_event_id"),
    )
    for column in (
        "camera_id",
        "zone_id",
        "virtual_line_id",
        "tracking_id",
        "status",
        "direction",
        "captured_at",
    ):
        op.create_index(
            f"ix_capture_events_{column}", "capture_events", [column]
        )

    op.create_table(
        "evidence_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_event_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("asset_type", asset_type, nullable=False),
        sa.Column(
            "sequence_index", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "integrity_status",
            integrity_status,
            nullable=False,
            server_default="VERIFIED",
        ),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column(
            "size_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "asset_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "retention_until", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "sequence_index >= 0", name="ck_evidence_asset_sequence"
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name="ck_evidence_asset_size"
        ),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_evidence_asset_checksum",
        ),
        sa.ForeignKeyConstraint(
            ["capture_event_id"], ["capture_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_snapshot_id"], ["snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint(
            "capture_event_id",
            "asset_type",
            "sequence_index",
            name="uq_evidence_capture_type_sequence",
        ),
    )
    for column in (
        "capture_event_id",
        "legacy_snapshot_id",
        "asset_type",
        "checksum_sha256",
        "integrity_status",
        "is_primary",
        "captured_at",
        "retention_until",
        "deleted_at",
    ):
        op.create_index(
            f"ix_evidence_assets_{column}", "evidence_assets", [column]
        )

    op.execute(
        """
        INSERT INTO capture_events (
            id,
            idempotency_key,
            source_event_id,
            camera_id,
            zone_id,
            virtual_line_id,
            tracking_id,
            status,
            direction,
            bbox,
            centroid,
            capture_quality,
            capture_metadata,
            captured_at,
            failed_at,
            error_message,
            attempt_count,
            created_at,
            updated_at
        )
        SELECT
            event.id,
            'legacy-event:' || event.id::text,
            event.id,
            tracking.camera_id,
            (
                SELECT mapping.zone_id
                FROM camera_zone_mappings AS mapping
                WHERE mapping.camera_id = tracking.camera_id
                  AND mapping.enabled = true
                ORDER BY mapping.is_primary DESC, mapping.created_at
                LIMIT 1
            ),
            (
                SELECT line.id
                FROM virtual_lines AS line
                WHERE line.camera_id = tracking.camera_id
                  AND line.line_key = event.line_id
                ORDER BY line.is_primary DESC, line.created_at
                LIMIT 1
            ),
            event.tracking_id,
            CASE
                WHEN snapshot.id IS NULL
                    THEN 'FAILED'::capture_event_status
                ELSE 'CAPTURED'::capture_event_status
            END,
            event.event_metadata->>'direction',
            snapshot.bbox::jsonb,
            event.centroid::jsonb,
            jsonb_build_object(
                'detector_confidence',
                event.event_metadata->'confidence'
            ),
            jsonb_build_object(
                'legacy_backfill', true,
                'event_type', event.event_type::text,
                'line_id', event.line_id,
                'byte_track_id', event.event_metadata->'byte_track_id'
            ),
            event.occurred_at,
            CASE WHEN snapshot.id IS NULL THEN event.occurred_at ELSE NULL END,
            CASE
                WHEN snapshot.id IS NULL
                    THEN COALESCE(
                        event.event_metadata->>'snapshot_error',
                        'Legacy event has no snapshot'
                    )
                ELSE NULL
            END,
            0,
            event.created_at,
            event.created_at
        FROM events AS event
        JOIN trackings AS tracking ON tracking.id = event.tracking_id
        LEFT JOIN snapshots AS snapshot ON snapshot.event_id = event.id
        """
    )
    op.execute(
        """
        INSERT INTO evidence_assets (
            id,
            capture_event_id,
            legacy_snapshot_id,
            asset_type,
            sequence_index,
            storage_key,
            checksum_sha256,
            integrity_status,
            mime_type,
            size_bytes,
            is_primary,
            asset_metadata,
            captured_at,
            created_at
        )
        SELECT
            snapshot.id,
            snapshot.event_id,
            snapshot.id,
            'ANNOTATED_SNAPSHOT'::evidence_asset_type,
            0,
            snapshot.image_path,
            NULL,
            'UNVERIFIED'::evidence_integrity_status,
            'image/jpeg',
            0,
            true,
            jsonb_build_object('legacy_backfill', true),
            snapshot.saved_at,
            snapshot.saved_at
        FROM snapshots AS snapshot
        """
    )
    op.execute(
        """
        INSERT INTO evidence_assets (
            id,
            capture_event_id,
            legacy_snapshot_id,
            asset_type,
            sequence_index,
            storage_key,
            checksum_sha256,
            integrity_status,
            mime_type,
            size_bytes,
            is_primary,
            asset_metadata,
            captured_at,
            created_at
        )
        SELECT
            gen_random_uuid(),
            snapshot.event_id,
            snapshot.id,
            'METADATA_JSON'::evidence_asset_type,
            0,
            snapshot.metadata_path,
            NULL,
            'UNVERIFIED'::evidence_integrity_status,
            'application/json',
            0,
            false,
            jsonb_build_object('legacy_backfill', true),
            snapshot.saved_at,
            snapshot.saved_at
        FROM snapshots AS snapshot
        WHERE snapshot.metadata_path <> snapshot.image_path
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_evidence_asset_identity()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.capture_event_id IS DISTINCT FROM OLD.capture_event_id
               OR NEW.asset_type IS DISTINCT FROM OLD.asset_type
               OR NEW.sequence_index IS DISTINCT FROM OLD.sequence_index
               OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
               OR NEW.captured_at IS DISTINCT FROM OLD.captured_at THEN
                RAISE EXCEPTION 'Evidence identity and checksum are immutable';
            END IF;
            IF NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256
               AND NOT (
                   OLD.checksum_sha256 IS NULL
                   AND OLD.integrity_status = 'UNVERIFIED'
               ) THEN
                RAISE EXCEPTION 'Evidence checksum is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_asset_immutable
        BEFORE UPDATE ON evidence_assets
        FOR EACH ROW EXECUTE FUNCTION protect_evidence_asset_identity()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_evidence_asset_immutable ON evidence_assets"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_evidence_asset_identity()")
    op.drop_table("evidence_assets")
    op.drop_table("capture_events")
    sa.Enum(name="evidence_integrity_status").drop(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(name="evidence_asset_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="capture_event_status").drop(op.get_bind(), checkfirst=True)
