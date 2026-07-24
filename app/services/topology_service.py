"""Business rules and audited mutations for factory topology."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models import (
    Building,
    CameraRole,
    CameraZoneMapping,
    User,
    VirtualLine,
    VirtualLineType,
    Zone,
    ZoneAdjacency,
)
from app.models.topology_rules import validate_virtual_line_geometry
from app.repository.audit_repository import AuditRepository
from app.repository.topology_repository import TopologyRepository


class TopologyNotFoundError(LookupError):
    pass


class TopologyConflictError(ValueError):
    pass


class TopologyValidationError(ValueError):
    pass


class TopologyService:
    def __init__(self, repository: TopologyRepository) -> None:
        self.repository = repository
        self.audit = AuditRepository(repository.session)

    async def create_building(
        self, payload: Any, actor: User
    ) -> Building:
        if await self.repository.find_building(code=payload.code, name=payload.name):
            raise TopologyConflictError("Building code or name already exists")
        building = Building(**payload.model_dump())
        await self.repository.add(building)
        await self._record(actor, "BUILDING_CREATED", building, {"code": building.code})
        await self._commit()
        return building

    async def update_building(
        self, building_id: UUID, payload: Any, actor: User
    ) -> Building:
        building = await self._building(building_id)
        changes = payload.model_dump(exclude_unset=True)
        duplicate = await self.repository.find_building(
            code=changes.get("code"), name=changes.get("name")
        )
        if duplicate is not None and duplicate.id != building.id:
            raise TopologyConflictError("Building code or name already exists")
        self._apply(building, changes)
        await self._record(
            actor, "BUILDING_UPDATED", building, {"fields": sorted(changes)}
        )
        await self._commit()
        return building

    async def archive_building(self, building_id: UUID, actor: User) -> None:
        building = await self._building(building_id)
        building.enabled = False
        await self.repository.disable_building_zones(building.id)
        await self._record(actor, "BUILDING_ARCHIVED", building)
        await self._commit()

    async def create_zone(self, payload: Any, actor: User) -> Zone:
        await self._building(payload.building_id)
        if await self.repository.find_zone(payload.building_id, payload.code):
            raise TopologyConflictError("Zone code already exists in this building")
        zone = Zone(**self._dump(payload, polygon_fields={"roi_polygon"}))
        await self.repository.add(zone)
        await self._record(actor, "ZONE_CREATED", zone, {"code": zone.code})
        await self._commit()
        return zone

    async def update_zone(
        self, zone_id: UUID, payload: Any, actor: User
    ) -> Zone:
        zone = await self._zone(zone_id)
        changes = self._dump(
            payload, exclude_unset=True, polygon_fields={"roi_polygon"}
        )
        building_id = changes.get("building_id", zone.building_id)
        await self._building(building_id)
        code = changes.get("code", zone.code)
        duplicate = await self.repository.find_zone(building_id, code)
        if duplicate is not None and duplicate.id != zone.id:
            raise TopologyConflictError("Zone code already exists in this building")
        self._apply(zone, changes)
        await self._record(actor, "ZONE_UPDATED", zone, {"fields": sorted(changes)})
        await self._commit()
        return zone

    async def archive_zone(self, zone_id: UUID, actor: User) -> None:
        zone = await self._zone(zone_id)
        zone.enabled = False
        await self._record(actor, "ZONE_ARCHIVED", zone)
        await self._commit()

    async def create_camera_role(
        self, payload: Any, actor: User
    ) -> CameraRole:
        await self._camera(payload.camera_id)
        if await self.repository.find_camera_role(payload.camera_id, payload.role):
            raise TopologyConflictError("Camera role already exists")
        role = CameraRole(**payload.model_dump())
        await self.repository.add(role)
        await self._record(
            actor, "CAMERA_ROLE_CREATED", role, {"role": role.role.value}
        )
        await self._commit()
        return role

    async def update_camera_role(
        self, role_id: UUID, payload: Any, actor: User
    ) -> CameraRole:
        role = await self._camera_role(role_id)
        changes = payload.model_dump(exclude_unset=True)
        self._apply(role, changes)
        await self._record(
            actor, "CAMERA_ROLE_UPDATED", role, {"fields": sorted(changes)}
        )
        await self._commit()
        return role

    async def delete_camera_role(self, role_id: UUID, actor: User) -> None:
        role = await self._camera_role(role_id)
        await self._record(
            actor, "CAMERA_ROLE_DELETED", role, {"role": role.role.value}
        )
        await self.repository.delete(role)
        await self._commit()

    async def create_camera_mapping(
        self, payload: Any, actor: User
    ) -> CameraZoneMapping:
        camera = await self._camera(payload.camera_id)
        zone = await self._zone(payload.zone_id)
        if await self.repository.find_camera_mapping(payload.camera_id, payload.zone_id):
            raise TopologyConflictError("Camera is already mapped to this zone")
        mapping = CameraZoneMapping(
            **self._dump(payload, polygon_fields={"coverage_polygon"})
        )
        await self.repository.add(mapping)
        if mapping.is_primary:
            await self.repository.clear_primary_camera_mapping(
                mapping.camera_id, except_id=mapping.id
            )
            self._sync_legacy_camera_location(camera, zone)
        await self._record(
            actor,
            "CAMERA_ZONE_MAPPING_CREATED",
            mapping,
            {"camera_id": str(mapping.camera_id), "zone_id": str(mapping.zone_id)},
        )
        await self._commit()
        return mapping

    async def update_camera_mapping(
        self,
        mapping_id: UUID,
        payload: Any,
        actor: User,
    ) -> CameraZoneMapping:
        mapping = await self._camera_mapping(mapping_id)
        changes = self._dump(
            payload, exclude_unset=True, polygon_fields={"coverage_polygon"}
        )
        self._apply(mapping, changes)
        if mapping.is_primary:
            await self.repository.clear_primary_camera_mapping(
                mapping.camera_id, except_id=mapping.id
            )
            camera = await self._camera(mapping.camera_id)
            zone = await self._zone(mapping.zone_id)
            self._sync_legacy_camera_location(camera, zone)
        await self._record(
            actor,
            "CAMERA_ZONE_MAPPING_UPDATED",
            mapping,
            {"fields": sorted(changes)},
        )
        await self._commit()
        return mapping

    async def delete_camera_mapping(self, mapping_id: UUID, actor: User) -> None:
        mapping = await self._camera_mapping(mapping_id)
        await self._record(actor, "CAMERA_ZONE_MAPPING_DELETED", mapping)
        await self.repository.delete(mapping)
        await self._commit()

    async def create_adjacency(
        self, payload: Any, actor: User
    ) -> ZoneAdjacency:
        await self._zone(payload.source_zone_id)
        await self._zone(payload.target_zone_id)
        if await self.repository.find_adjacency(
            payload.source_zone_id, payload.target_zone_id
        ):
            raise TopologyConflictError("Directed zone adjacency already exists")
        adjacency = ZoneAdjacency(**payload.model_dump())
        await self.repository.add(adjacency)
        await self._record(
            actor,
            "ZONE_ADJACENCY_CREATED",
            adjacency,
            {
                "source_zone_id": str(adjacency.source_zone_id),
                "target_zone_id": str(adjacency.target_zone_id),
            },
        )
        await self._commit()
        return adjacency

    async def update_adjacency(
        self, adjacency_id: UUID, payload: Any, actor: User
    ) -> ZoneAdjacency:
        adjacency = await self._adjacency(adjacency_id)
        changes = payload.model_dump(exclude_unset=True)
        minimum = changes.get(
            "minimum_travel_seconds", adjacency.minimum_travel_seconds
        )
        maximum = changes.get(
            "maximum_travel_seconds", adjacency.maximum_travel_seconds
        )
        if maximum < minimum:
            raise TopologyValidationError(
                "Maximum travel time must not be below minimum travel time"
            )
        self._apply(adjacency, changes)
        await self._record(
            actor, "ZONE_ADJACENCY_UPDATED", adjacency, {"fields": sorted(changes)}
        )
        await self._commit()
        return adjacency

    async def delete_adjacency(self, adjacency_id: UUID, actor: User) -> None:
        adjacency = await self._adjacency(adjacency_id)
        await self._record(actor, "ZONE_ADJACENCY_DELETED", adjacency)
        await self.repository.delete(adjacency)
        await self._commit()

    async def create_virtual_line(
        self, payload: Any, actor: User
    ) -> VirtualLine:
        camera = await self._camera(payload.camera_id)
        if await self.repository.find_virtual_line(payload.camera_id, payload.line_key):
            raise TopologyConflictError("Virtual line key already exists for this camera")
        await self._validate_line_topology(
            payload.camera_id, payload.from_zone_id, payload.to_zone_id
        )
        line = VirtualLine(
            **self._dump(payload, polygon_fields={"points"})
        )
        await self.repository.add(line)
        if line.is_primary:
            await self.repository.clear_primary_virtual_line(
                line.camera_id, except_id=line.id
            )
            self._sync_legacy_crossing(camera, line)
        await self._record(
            actor,
            "VIRTUAL_LINE_CREATED",
            line,
            {"camera_id": str(line.camera_id), "line_key": line.line_key},
        )
        await self._commit()
        return line

    async def update_virtual_line(
        self, line_id: UUID, payload: Any, actor: User
    ) -> VirtualLine:
        line = await self._virtual_line(line_id)
        changes = self._dump(
            payload, exclude_unset=True, polygon_fields={"points"}
        )
        line_key = changes.get("line_key", line.line_key)
        duplicate = await self.repository.find_virtual_line(line.camera_id, line_key)
        if duplicate is not None and duplicate.id != line.id:
            raise TopologyConflictError("Virtual line key already exists for this camera")
        line_type = changes.get("line_type", line.line_type)
        position = changes.get("position", line.position)
        points = changes.get("points", line.points)
        enter_direction = changes.get("enter_direction", line.enter_direction)
        from_zone_id = changes.get("from_zone_id", line.from_zone_id)
        to_zone_id = changes.get("to_zone_id", line.to_zone_id)
        validate_virtual_line_geometry(
            line_type,
            position,
            points,
            enter_direction,
            from_zone_id,
            to_zone_id,
        )
        await self._validate_line_topology(
            line.camera_id, from_zone_id, to_zone_id
        )
        self._apply(line, changes)
        if line.is_primary:
            await self.repository.clear_primary_virtual_line(
                line.camera_id, except_id=line.id
            )
            camera = await self._camera(line.camera_id)
            self._sync_legacy_crossing(camera, line)
        await self._record(
            actor, "VIRTUAL_LINE_UPDATED", line, {"fields": sorted(changes)}
        )
        await self._commit()
        return line

    async def delete_virtual_line(self, line_id: UUID, actor: User) -> None:
        line = await self._virtual_line(line_id)
        camera = await self._camera(line.camera_id)
        was_primary = line.is_primary
        await self._record(actor, "VIRTUAL_LINE_DELETED", line)
        await self.repository.delete(line)
        if was_primary:
            camera.crossing_config = None
        await self._commit()

    async def get_legacy_crossing_config(
        self, camera_id: UUID
    ) -> dict[str, Any] | None:
        camera = await self._camera(camera_id)
        line = await self.repository.get_primary_virtual_line(camera_id)
        if line is not None:
            return self._line_crossing_mapping(line)
        if camera.crossing_config:
            return camera.crossing_config
        return None

    async def update_legacy_crossing_config(
        self, camera_id: UUID, payload: Any, actor: User
    ) -> Any:
        camera = await self._camera(camera_id)
        line = await self.repository.get_primary_virtual_line(camera_id)
        if line is None:
            duplicate = await self.repository.find_virtual_line(
                camera_id, payload.line_id
            )
            line = duplicate or VirtualLine(
                camera_id=camera_id,
                line_key=payload.line_id,
                name=payload.line_id,
                line_type=VirtualLineType(payload.line_type),
                position=payload.position,
                points=[point.model_dump() for point in payload.polygon_points],
                enter_direction=payload.enter_direction,
                is_primary=True,
                display_order=0,
                enabled=payload.enabled,
            )
            if duplicate is None:
                await self.repository.add(line)
        line.line_key = payload.line_id
        line.name = payload.line_id
        line.line_type = VirtualLineType(payload.line_type)
        line.position = payload.position
        line.points = [point.model_dump() for point in payload.polygon_points]
        line.enter_direction = payload.enter_direction
        line.is_primary = True
        line.enabled = payload.enabled
        await self.repository.clear_primary_virtual_line(
            camera_id, except_id=line.id
        )
        self._sync_legacy_crossing(camera, line)
        await self._record(
            actor,
            "CAMERA_CROSSING_CONFIG_UPDATED",
            line,
            {
                "camera_id": str(camera_id),
                "line_key": line.line_key,
                "source": "legacy-compatible-api",
            },
        )
        await self._commit()
        return payload

    async def validate_topology(self) -> dict[str, Any]:
        zones, _ = await self.repository.list_zones(
            building_id=None, enabled=True, search=None, offset=0, limit=10000
        )
        mappings = await self.repository.list_camera_mappings()
        adjacencies = await self.repository.list_adjacencies()
        lines = await self.repository.list_virtual_lines()
        errors: list[str] = []
        warnings: list[str] = []
        mapped_zone_ids = {item.zone_id for item in mappings if item.enabled}
        mapped_camera_zones: dict[UUID, set[UUID]] = {}
        for mapping in mappings:
            if mapping.enabled:
                mapped_camera_zones.setdefault(mapping.camera_id, set()).add(
                    mapping.zone_id
                )
        routes = {
            (item.source_zone_id, item.target_zone_id)
            for item in adjacencies
            if item.enabled
        }
        routes.update(
            (item.target_zone_id, item.source_zone_id)
            for item in adjacencies
            if item.enabled and item.bidirectional
        )
        for zone in zones:
            if zone.id not in mapped_zone_ids:
                warnings.append(f"Zone {zone.code} has no active camera coverage")
        for line in lines:
            if not line.enabled:
                continue
            camera_zones = mapped_camera_zones.get(line.camera_id, set())
            endpoint_zones = {
                item for item in (line.from_zone_id, line.to_zone_id) if item
            }
            if endpoint_zones and not camera_zones.intersection(endpoint_zones):
                errors.append(
                    f"Virtual line {line.line_key} camera does not cover an endpoint zone"
                )
            if (
                line.from_zone_id
                and line.to_zone_id
                and (line.from_zone_id, line.to_zone_id) not in routes
            ):
                errors.append(
                    f"Virtual line {line.line_key} connects non-adjacent zones"
                )
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    async def _validate_line_topology(
        self,
        camera_id: UUID,
        from_zone_id: UUID | None,
        to_zone_id: UUID | None,
    ) -> None:
        endpoint_ids = {item for item in (from_zone_id, to_zone_id) if item}
        for zone_id in endpoint_ids:
            await self._zone(zone_id)
        mappings = await self.repository.list_camera_mappings(camera_id=camera_id)
        camera_zone_ids = {item.zone_id for item in mappings if item.enabled}
        if endpoint_ids and not camera_zone_ids.intersection(endpoint_ids):
            raise TopologyValidationError(
                "Camera must cover at least one endpoint zone"
            )
        if (
            from_zone_id is not None
            and to_zone_id is not None
            and not await self.repository.route_allowed(from_zone_id, to_zone_id)
        ):
            raise TopologyValidationError(
                "Virtual line endpoints must be connected by an enabled adjacency"
            )

    async def _building(self, entity_id: UUID) -> Building:
        entity = await self.repository.get_building(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Building not found")
        return entity

    async def _zone(self, entity_id: UUID) -> Zone:
        entity = await self.repository.get_zone(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Zone not found")
        return entity

    async def _camera(self, entity_id: UUID) -> Any:
        entity = await self.repository.get_camera(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Camera not found")
        return entity

    async def _camera_role(self, entity_id: UUID) -> CameraRole:
        entity = await self.repository.get_camera_role(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Camera role not found")
        return entity

    async def _camera_mapping(self, entity_id: UUID) -> CameraZoneMapping:
        entity = await self.repository.get_camera_mapping(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Camera-zone mapping not found")
        return entity

    async def _adjacency(self, entity_id: UUID) -> ZoneAdjacency:
        entity = await self.repository.get_adjacency(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Zone adjacency not found")
        return entity

    async def _virtual_line(self, entity_id: UUID) -> VirtualLine:
        entity = await self.repository.get_virtual_line(entity_id)
        if entity is None:
            raise TopologyNotFoundError("Virtual line not found")
        return entity

    async def _record(
        self,
        actor: User,
        action: str,
        entity: Any,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self.audit.record(
            actor_user_id=actor.id,
            action=action,
            resource_type=entity.__tablename__,
            resource_id=str(entity.id),
            details=details,
        )

    async def _commit(self) -> None:
        try:
            await self.repository.session.commit()
        except IntegrityError as error:
            await self.repository.session.rollback()
            raise TopologyConflictError(
                "Topology configuration conflicts with existing data"
            ) from error

    @staticmethod
    def _apply(entity: Any, changes: dict[str, Any]) -> None:
        for field, value in changes.items():
            setattr(entity, field, value.strip() if isinstance(value, str) else value)

    @staticmethod
    def _dump(
        payload: Any,
        *,
        exclude_unset: bool = False,
        polygon_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        values = payload.model_dump(exclude_unset=exclude_unset)
        for field in polygon_fields or set():
            if field in values and values[field] is not None:
                values[field] = [
                    point.model_dump() if hasattr(point, "model_dump") else point
                    for point in values[field]
                ]
        return values

    @staticmethod
    def _sync_legacy_camera_location(camera: Any, zone: Zone) -> None:
        camera.building = zone.building.name
        camera.floor = zone.floor_name
        camera.zone = zone.name
        camera.location = zone.room_name or zone.area_name or zone.name

    @staticmethod
    def _sync_legacy_crossing(camera: Any, line: VirtualLine) -> None:
        camera.crossing_config = TopologyService._line_crossing_mapping(line)

    @staticmethod
    def _line_crossing_mapping(line: VirtualLine) -> dict[str, Any]:
        return {
            "enabled": line.enabled,
            "line_id": line.line_key,
            "line_type": line.line_type.value,
            "position": line.position,
            "enter_direction": line.enter_direction,
            "polygon_points": line.points or [],
        }
