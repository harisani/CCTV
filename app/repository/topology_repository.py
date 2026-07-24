"""Async persistence operations for factory and camera topology."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Building,
    Camera,
    CameraRole,
    CameraZoneMapping,
    VirtualLine,
    Zone,
    ZoneAdjacency,
)


class TopologyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_building(self, building_id: UUID) -> Building | None:
        return await self.session.get(Building, building_id)

    async def find_building(
        self, *, code: str | None = None, name: str | None = None
    ) -> Building | None:
        conditions = []
        if code is not None:
            conditions.append(func.lower(Building.code) == code.lower())
        if name is not None:
            conditions.append(func.lower(Building.name) == name.lower())
        if not conditions:
            return None
        return await self.session.scalar(select(Building).where(or_(*conditions)))

    async def list_buildings(
        self, *, enabled: bool | None, offset: int, limit: int
    ) -> tuple[list[Building], int]:
        statement = select(Building)
        if enabled is not None:
            statement = statement.where(Building.enabled.is_(enabled))
        total = (
            await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        page = statement.order_by(Building.name).offset(offset).limit(limit)
        return list((await self.session.scalars(page)).all()), total

    async def get_zone(self, zone_id: UUID) -> Zone | None:
        return await self.session.scalar(
            select(Zone)
            .options(selectinload(Zone.building))
            .where(Zone.id == zone_id)
        )

    async def disable_building_zones(self, building_id: UUID) -> None:
        await self.session.execute(
            update(Zone)
            .where(Zone.building_id == building_id)
            .values(enabled=False)
        )

    async def find_zone(self, building_id: UUID, code: str) -> Zone | None:
        return await self.session.scalar(
            select(Zone).where(
                Zone.building_id == building_id,
                func.lower(Zone.code) == code.lower(),
            )
        )

    async def list_zones(
        self,
        *,
        building_id: UUID | None,
        enabled: bool | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Zone], int]:
        statement = select(Zone)
        if building_id is not None:
            statement = statement.where(Zone.building_id == building_id)
        if enabled is not None:
            statement = statement.where(Zone.enabled.is_(enabled))
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Zone.code.ilike(pattern),
                    Zone.name.ilike(pattern),
                    Zone.floor_name.ilike(pattern),
                    Zone.area_name.ilike(pattern),
                    Zone.room_name.ilike(pattern),
                )
            )
        total = (
            await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        page = statement.order_by(Zone.building_id, Zone.name).offset(offset).limit(limit)
        return list((await self.session.scalars(page)).all()), total

    async def get_camera(self, camera_id: UUID) -> Camera | None:
        return await self.session.get(Camera, camera_id)

    async def get_camera_role(self, role_id: UUID) -> CameraRole | None:
        return await self.session.get(CameraRole, role_id)

    async def find_camera_role(self, camera_id: UUID, role: object) -> CameraRole | None:
        return await self.session.scalar(
            select(CameraRole).where(
                CameraRole.camera_id == camera_id, CameraRole.role == role
            )
        )

    async def list_camera_roles(
        self, *, camera_id: UUID | None
    ) -> list[CameraRole]:
        statement = select(CameraRole)
        if camera_id is not None:
            statement = statement.where(CameraRole.camera_id == camera_id)
        return list(
            (
                await self.session.scalars(
                    statement.order_by(CameraRole.camera_id, CameraRole.role)
                )
            ).all()
        )

    async def get_camera_mapping(
        self, mapping_id: UUID
    ) -> CameraZoneMapping | None:
        return await self.session.get(CameraZoneMapping, mapping_id)

    async def find_camera_mapping(
        self, camera_id: UUID, zone_id: UUID
    ) -> CameraZoneMapping | None:
        return await self.session.scalar(
            select(CameraZoneMapping).where(
                CameraZoneMapping.camera_id == camera_id,
                CameraZoneMapping.zone_id == zone_id,
            )
        )

    async def list_camera_mappings(
        self,
        *,
        camera_id: UUID | None = None,
        zone_id: UUID | None = None,
    ) -> list[CameraZoneMapping]:
        statement = select(CameraZoneMapping)
        if camera_id is not None:
            statement = statement.where(CameraZoneMapping.camera_id == camera_id)
        if zone_id is not None:
            statement = statement.where(CameraZoneMapping.zone_id == zone_id)
        return list(
            (
                await self.session.scalars(
                    statement.order_by(
                        CameraZoneMapping.camera_id,
                        CameraZoneMapping.is_primary.desc(),
                    )
                )
            ).all()
        )

    async def clear_primary_camera_mapping(
        self, camera_id: UUID, *, except_id: UUID | None = None
    ) -> None:
        statement = update(CameraZoneMapping).where(
            CameraZoneMapping.camera_id == camera_id
        )
        if except_id is not None:
            statement = statement.where(CameraZoneMapping.id != except_id)
        await self.session.execute(statement.values(is_primary=False))

    async def get_adjacency(self, adjacency_id: UUID) -> ZoneAdjacency | None:
        return await self.session.get(ZoneAdjacency, adjacency_id)

    async def find_adjacency(
        self, source_zone_id: UUID, target_zone_id: UUID
    ) -> ZoneAdjacency | None:
        return await self.session.scalar(
            select(ZoneAdjacency).where(
                ZoneAdjacency.source_zone_id == source_zone_id,
                ZoneAdjacency.target_zone_id == target_zone_id,
            )
        )

    async def route_allowed(
        self, source_zone_id: UUID, target_zone_id: UUID
    ) -> bool:
        route = await self.session.scalar(
            select(ZoneAdjacency.id).where(
                ZoneAdjacency.enabled.is_(True),
                or_(
                    (
                        (ZoneAdjacency.source_zone_id == source_zone_id)
                        & (ZoneAdjacency.target_zone_id == target_zone_id)
                    ),
                    (
                        ZoneAdjacency.bidirectional.is_(True)
                        & (ZoneAdjacency.source_zone_id == target_zone_id)
                        & (ZoneAdjacency.target_zone_id == source_zone_id)
                    ),
                ),
            )
        )
        return route is not None

    async def list_adjacencies(
        self, *, zone_id: UUID | None = None
    ) -> list[ZoneAdjacency]:
        statement = select(ZoneAdjacency)
        if zone_id is not None:
            statement = statement.where(
                or_(
                    ZoneAdjacency.source_zone_id == zone_id,
                    ZoneAdjacency.target_zone_id == zone_id,
                )
            )
        return list(
            (
                await self.session.scalars(
                    statement.order_by(
                        ZoneAdjacency.source_zone_id,
                        ZoneAdjacency.target_zone_id,
                    )
                )
            ).all()
        )

    async def get_virtual_line(self, line_id: UUID) -> VirtualLine | None:
        return await self.session.get(VirtualLine, line_id)

    async def find_virtual_line(
        self, camera_id: UUID, line_key: str
    ) -> VirtualLine | None:
        return await self.session.scalar(
            select(VirtualLine).where(
                VirtualLine.camera_id == camera_id,
                func.lower(VirtualLine.line_key) == line_key.lower(),
            )
        )

    async def get_primary_virtual_line(self, camera_id: UUID) -> VirtualLine | None:
        return await self.session.scalar(
            select(VirtualLine)
            .where(
                VirtualLine.camera_id == camera_id,
                VirtualLine.is_primary.is_(True),
            )
            .order_by(VirtualLine.display_order, VirtualLine.created_at)
            .limit(1)
        )

    async def list_virtual_lines(
        self,
        *,
        camera_id: UUID | None = None,
        zone_id: UUID | None = None,
    ) -> list[VirtualLine]:
        statement = select(VirtualLine)
        if camera_id is not None:
            statement = statement.where(VirtualLine.camera_id == camera_id)
        if zone_id is not None:
            statement = statement.where(
                or_(
                    VirtualLine.from_zone_id == zone_id,
                    VirtualLine.to_zone_id == zone_id,
                )
            )
        return list(
            (
                await self.session.scalars(
                    statement.order_by(
                        VirtualLine.camera_id,
                        VirtualLine.is_primary.desc(),
                        VirtualLine.display_order,
                    )
                )
            ).all()
        )

    async def clear_primary_virtual_line(
        self, camera_id: UUID, *, except_id: UUID | None = None
    ) -> None:
        statement = update(VirtualLine).where(VirtualLine.camera_id == camera_id)
        if except_id is not None:
            statement = statement.where(VirtualLine.id != except_id)
        await self.session.execute(statement.values(is_primary=False))

    async def add(self, entity: object) -> None:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)

    async def delete(self, entity: object) -> None:
        await self.session.delete(entity)
