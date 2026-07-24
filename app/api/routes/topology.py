"""REST configuration API for buildings, zones, and camera topology."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_topology_service
from app.api.schemas import Page
from app.api.security import require_authenticated_user, require_roles
from app.api.topology_schemas import (
    BuildingCreate,
    BuildingResponse,
    BuildingUpdate,
    CameraRoleCreate,
    CameraRoleResponse,
    CameraRoleUpdate,
    CameraZoneMappingCreate,
    CameraZoneMappingResponse,
    CameraZoneMappingUpdate,
    TopologyGraphResponse,
    TopologyValidationResponse,
    VirtualLineCreate,
    VirtualLineResponse,
    VirtualLineUpdate,
    ZoneAdjacencyCreate,
    ZoneAdjacencyResponse,
    ZoneAdjacencyUpdate,
    ZoneCreate,
    ZoneResponse,
    ZoneUpdate,
)
from app.models import (
    Building,
    CameraRole,
    CameraZoneMapping,
    User,
    UserRole,
    VirtualLine,
    Zone,
    ZoneAdjacency,
)
from app.services.topology_service import TopologyService

router = APIRouter(
    prefix="/topology", dependencies=[Depends(require_authenticated_user)]
)
admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)


@router.get("/buildings", response_model=Page[BuildingResponse])
async def list_buildings(
    enabled: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    service: TopologyService = Depends(get_topology_service),
) -> Page[BuildingResponse]:
    items, total = await service.repository.list_buildings(
        enabled=enabled, offset=offset, limit=limit
    )
    return Page[BuildingResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "/buildings",
    response_model=BuildingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_building(
    payload: BuildingCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Building:
    return await service.create_building(payload, actor)


@router.patch("/buildings/{building_id}", response_model=BuildingResponse)
async def update_building(
    building_id: UUID,
    payload: BuildingUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Building:
    return await service.update_building(building_id, payload, actor)


@router.delete(
    "/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def archive_building(
    building_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.archive_building(building_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/zones", response_model=Page[ZoneResponse])
async def list_zones(
    building_id: UUID | None = None,
    enabled: bool | None = None,
    search: str | None = Query(default=None, max_length=150),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    service: TopologyService = Depends(get_topology_service),
) -> Page[ZoneResponse]:
    items, total = await service.repository.list_zones(
        building_id=building_id,
        enabled=enabled,
        search=search,
        offset=offset,
        limit=limit,
    )
    return Page[ZoneResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "/zones", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED
)
async def create_zone(
    payload: ZoneCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Zone:
    return await service.create_zone(payload, actor)


@router.patch("/zones/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    zone_id: UUID,
    payload: ZoneUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Zone:
    return await service.update_zone(zone_id, payload, actor)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_zone(
    zone_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.archive_zone(zone_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/camera-roles", response_model=list[CameraRoleResponse])
async def list_camera_roles(
    camera_id: UUID | None = None,
    service: TopologyService = Depends(get_topology_service),
) -> list[CameraRole]:
    return await service.repository.list_camera_roles(camera_id=camera_id)


@router.post(
    "/camera-roles",
    response_model=CameraRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_camera_role(
    payload: CameraRoleCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> CameraRole:
    return await service.create_camera_role(payload, actor)


@router.patch("/camera-roles/{role_id}", response_model=CameraRoleResponse)
async def update_camera_role(
    role_id: UUID,
    payload: CameraRoleUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> CameraRole:
    return await service.update_camera_role(role_id, payload, actor)


@router.delete(
    "/camera-roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_camera_role(
    role_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.delete_camera_role(role_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/camera-zone-mappings", response_model=list[CameraZoneMappingResponse]
)
async def list_camera_zone_mappings(
    camera_id: UUID | None = None,
    zone_id: UUID | None = None,
    service: TopologyService = Depends(get_topology_service),
) -> list[CameraZoneMapping]:
    return await service.repository.list_camera_mappings(
        camera_id=camera_id, zone_id=zone_id
    )


@router.post(
    "/camera-zone-mappings",
    response_model=CameraZoneMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_camera_zone_mapping(
    payload: CameraZoneMappingCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> CameraZoneMapping:
    return await service.create_camera_mapping(payload, actor)


@router.patch(
    "/camera-zone-mappings/{mapping_id}",
    response_model=CameraZoneMappingResponse,
)
async def update_camera_zone_mapping(
    mapping_id: UUID,
    payload: CameraZoneMappingUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> CameraZoneMapping:
    return await service.update_camera_mapping(mapping_id, payload, actor)


@router.delete(
    "/camera-zone-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_camera_zone_mapping(
    mapping_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.delete_camera_mapping(mapping_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/adjacencies", response_model=list[ZoneAdjacencyResponse])
async def list_zone_adjacencies(
    zone_id: UUID | None = None,
    service: TopologyService = Depends(get_topology_service),
) -> list[ZoneAdjacency]:
    return await service.repository.list_adjacencies(zone_id=zone_id)


@router.post(
    "/adjacencies",
    response_model=ZoneAdjacencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone_adjacency(
    payload: ZoneAdjacencyCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> ZoneAdjacency:
    return await service.create_adjacency(payload, actor)


@router.patch(
    "/adjacencies/{adjacency_id}", response_model=ZoneAdjacencyResponse
)
async def update_zone_adjacency(
    adjacency_id: UUID,
    payload: ZoneAdjacencyUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> ZoneAdjacency:
    return await service.update_adjacency(adjacency_id, payload, actor)


@router.delete(
    "/adjacencies/{adjacency_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_zone_adjacency(
    adjacency_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.delete_adjacency(adjacency_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/virtual-lines", response_model=list[VirtualLineResponse])
async def list_virtual_lines(
    camera_id: UUID | None = None,
    zone_id: UUID | None = None,
    service: TopologyService = Depends(get_topology_service),
) -> list[VirtualLine]:
    return await service.repository.list_virtual_lines(
        camera_id=camera_id, zone_id=zone_id
    )


@router.post(
    "/virtual-lines",
    response_model=VirtualLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_virtual_line(
    payload: VirtualLineCreate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> VirtualLine:
    return await service.create_virtual_line(payload, actor)


@router.patch("/virtual-lines/{line_id}", response_model=VirtualLineResponse)
async def update_virtual_line(
    line_id: UUID,
    payload: VirtualLineUpdate,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> VirtualLine:
    return await service.update_virtual_line(line_id, payload, actor)


@router.delete(
    "/virtual-lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_virtual_line(
    line_id: UUID,
    actor: User = Depends(admin),
    service: TopologyService = Depends(get_topology_service),
) -> Response:
    await service.delete_virtual_line(line_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/graph", response_model=TopologyGraphResponse)
async def get_topology_graph(
    service: TopologyService = Depends(get_topology_service),
) -> TopologyGraphResponse:
    buildings, _ = await service.repository.list_buildings(
        enabled=None, offset=0, limit=10000
    )
    zones, _ = await service.repository.list_zones(
        building_id=None,
        enabled=None,
        search=None,
        offset=0,
        limit=10000,
    )
    return TopologyGraphResponse(
        buildings=buildings,
        zones=zones,
        camera_mappings=await service.repository.list_camera_mappings(),
        adjacencies=await service.repository.list_adjacencies(),
        virtual_lines=await service.repository.list_virtual_lines(),
    )


@router.get("/validate", response_model=TopologyValidationResponse)
async def validate_topology(
    service: TopologyService = Depends(get_topology_service),
) -> TopologyValidationResponse:
    return await service.validate_topology()
