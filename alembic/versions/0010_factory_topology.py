"""building, zone, camera role, topology, and virtual line configuration

Revision ID: 0010_factory_topology
Revises: 0009_presence_sessions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_factory_topology"
down_revision: str | None = "0009_presence_sessions"
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
    zone_sensitivity = sa.Enum(
        "STANDARD", "RESTRICTED", "CRITICAL", name="zone_sensitivity"
    )
    processing_priority = sa.Enum(
        "LOW", "NORMAL", "HIGH", name="processing_priority"
    )
    camera_role_type = sa.Enum(
        "IDENTITY_CAPTURE",
        "TRANSITION",
        "OVERVIEW",
        "EVIDENCE",
        name="camera_role_type",
    )
    virtual_line_type = sa.Enum(
        "HORIZONTAL", "VERTICAL", "POLYGON", name="virtual_line_type"
    )

    op.create_table(
        "buildings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Jakarta",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    for column in ("code", "name", "enabled"):
        op.create_index(f"ix_buildings_{column}", "buildings", [column])

    op.create_table(
        "zones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("building_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("floor_name", sa.String(length=80), nullable=True),
        sa.Column("area_name", sa.String(length=120), nullable=True),
        sa.Column("room_name", sa.String(length=120), nullable=True),
        sa.Column(
            "roi_polygon",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "sensitivity",
            zone_sensitivity,
            nullable=False,
            server_default="STANDARD",
        ),
        sa.Column(
            "processing_priority",
            processing_priority,
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column(
            "retention_days", sa.Integer(), nullable=False, server_default="90"
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 3650", name="ck_zone_retention_days"
        ),
        sa.ForeignKeyConstraint(
            ["building_id"], ["buildings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "building_id", "code", name="uq_zone_building_code"
        ),
    )
    for column in (
        "building_id",
        "code",
        "name",
        "floor_name",
        "area_name",
        "room_name",
        "sensitivity",
        "processing_priority",
        "enabled",
    ):
        op.create_index(f"ix_zones_{column}", "zones", [column])

    op.create_table(
        "camera_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("role", camera_role_type, nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "role", name="uq_camera_role"),
    )
    for column in ("camera_id", "role", "enabled"):
        op.create_index(f"ix_camera_roles_{column}", "camera_roles", [column])

    op.create_table(
        "camera_zone_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column(
            "coverage_polygon",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zones.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "camera_id", "zone_id", name="uq_camera_zone_mapping"
        ),
    )
    for column in ("camera_id", "zone_id", "is_primary", "enabled"):
        op.create_index(
            f"ix_camera_zone_mappings_{column}",
            "camera_zone_mappings",
            [column],
        )
    op.execute(
        "CREATE UNIQUE INDEX uq_camera_zone_primary "
        "ON camera_zone_mappings (camera_id) WHERE is_primary IS TRUE"
    )

    op.create_table(
        "zone_adjacencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_zone_id", sa.Uuid(), nullable=False),
        sa.Column("target_zone_id", sa.Uuid(), nullable=False),
        sa.Column(
            "minimum_travel_seconds",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "maximum_travel_seconds",
            sa.Float(),
            nullable=False,
            server_default="300",
        ),
        sa.Column(
            "bidirectional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "source_zone_id <> target_zone_id",
            name="ck_zone_adjacency_distinct",
        ),
        sa.CheckConstraint(
            "minimum_travel_seconds >= 0",
            name="ck_zone_adjacency_minimum",
        ),
        sa.CheckConstraint(
            "maximum_travel_seconds >= minimum_travel_seconds",
            name="ck_zone_adjacency_maximum",
        ),
        sa.ForeignKeyConstraint(
            ["source_zone_id"], ["zones.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_zone_id"], ["zones.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_zone_id",
            "target_zone_id",
            name="uq_zone_adjacency_direction",
        ),
    )
    for column in ("source_zone_id", "target_zone_id", "enabled"):
        op.create_index(
            f"ix_zone_adjacencies_{column}",
            "zone_adjacencies",
            [column],
        )

    op.create_table(
        "virtual_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("line_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("line_type", virtual_line_type, nullable=False),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column(
            "points", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("enter_direction", sa.String(length=10), nullable=False),
        sa.Column("from_zone_id", sa.Uuid(), nullable=True),
        sa.Column("to_zone_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "display_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "from_zone_id IS NULL OR to_zone_id IS NULL "
            "OR from_zone_id <> to_zone_id",
            name="ck_virtual_line_distinct_zones",
        ),
        sa.CheckConstraint(
            "position IS NULL OR (position >= 0 AND position <= 1)",
            name="ck_virtual_line_position",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["from_zone_id"], ["zones.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["to_zone_id"], ["zones.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "camera_id", "line_key", name="uq_virtual_line_camera_key"
        ),
    )
    for column in (
        "camera_id",
        "line_key",
        "line_type",
        "from_zone_id",
        "to_zone_id",
        "is_primary",
        "enabled",
    ):
        op.create_index(
            f"ix_virtual_lines_{column}", "virtual_lines", [column]
        )
    op.execute(
        "CREATE UNIQUE INDEX uq_virtual_line_primary "
        "ON virtual_lines (camera_id) WHERE is_primary IS TRUE"
    )

    # Convert the existing free-text camera locations into a safe initial
    # topology. Legacy camera fields remain available during the transition.
    op.execute(
        """
        INSERT INTO buildings (id, code, name, timezone, enabled)
        SELECT gen_random_uuid(),
               'legacy-' || substr(md5(trim(building)), 1, 12),
               trim(building), 'Asia/Jakarta', TRUE
        FROM cameras
        WHERE building IS NOT NULL AND trim(building) <> ''
        GROUP BY trim(building)
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO zones (
            id, building_id, code, name, floor_name, sensitivity,
            processing_priority, retention_days, enabled
        )
        SELECT gen_random_uuid(), b.id,
               'legacy-' || substr(
                   md5(concat_ws('|', trim(c.building), trim(c.floor), trim(c.zone))),
                   1, 12
               ),
               trim(c.zone), nullif(trim(c.floor), ''),
               'STANDARD', 'NORMAL', 90, TRUE
        FROM cameras c
        JOIN buildings b ON b.name = trim(c.building)
        WHERE c.zone IS NOT NULL AND trim(c.zone) <> ''
        GROUP BY b.id, trim(c.building), trim(c.floor), trim(c.zone)
        ON CONFLICT (building_id, code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO camera_zone_mappings (
            id, camera_id, zone_id, is_primary, enabled
        )
        SELECT gen_random_uuid(), c.id, z.id, TRUE, TRUE
        FROM cameras c
        JOIN buildings b ON b.name = trim(c.building)
        JOIN zones z
          ON z.building_id = b.id
         AND z.code = 'legacy-' || substr(
             md5(concat_ws('|', trim(c.building), trim(c.floor), trim(c.zone))),
             1, 12
         )
        WHERE c.zone IS NOT NULL AND trim(c.zone) <> ''
        ON CONFLICT (camera_id, zone_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO virtual_lines (
            id, camera_id, line_key, name, line_type, position, points,
            enter_direction, is_primary, display_order, enabled
        )
        SELECT gen_random_uuid(), id,
               COALESCE(crossing_config->>'line_id', 'main-door'),
               COALESCE(crossing_config->>'line_id', 'Main transition'),
               upper(COALESCE(crossing_config->>'line_type', 'horizontal'))
                   ::virtual_line_type,
               CASE WHEN crossing_config->>'position' IS NULL THEN NULL
                    ELSE (crossing_config->>'position')::double precision END,
               crossing_config->'polygon_points',
               COALESCE(crossing_config->>'enter_direction', 'down'),
               TRUE, 0,
               COALESCE((crossing_config->>'enabled')::boolean, TRUE)
        FROM cameras
        WHERE crossing_config IS NOT NULL
        ON CONFLICT (camera_id, line_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("virtual_lines")
    op.drop_table("zone_adjacencies")
    op.drop_table("camera_zone_mappings")
    op.drop_table("camera_roles")
    op.drop_table("zones")
    op.drop_table("buildings")
    sa.Enum(name="virtual_line_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="camera_role_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="processing_priority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="zone_sensitivity").drop(op.get_bind(), checkfirst=True)
