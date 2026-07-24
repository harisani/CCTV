import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.topology_schemas import (
    CameraZoneMappingCreate,
    VirtualLineCreate,
    VirtualLineUpdate,
    ZoneAdjacencyCreate,
    ZoneCreate,
)
from app.app import create_app
from app.models import (
    Camera,
    VirtualLine,
    VirtualLineType,
    Zone,
    ZoneSensitivity,
)
from app.services.topology_service import (
    TopologyService,
    TopologyValidationError,
)


def test_phase2_routes_are_published_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/api/v1/topology/buildings" in paths
    assert "/api/v1/topology/zones" in paths
    assert "/api/v1/topology/camera-roles" in paths
    assert "/api/v1/topology/camera-zone-mappings" in paths
    assert "/api/v1/topology/adjacencies" in paths
    assert "/api/v1/topology/virtual-lines" in paths
    assert "/api/v1/topology/validate" in paths


def test_zone_polygon_uses_resolution_independent_coordinates() -> None:
    payload = ZoneCreate(
        building_id=uuid4(),
        code="MIXING",
        name="Mixing Area",
        roi_polygon=[
            {"x": 0.1, "y": 0.2},
            {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.9},
        ],
        sensitivity=ZoneSensitivity.RESTRICTED,
    )

    assert payload.roi_polygon is not None
    assert payload.roi_polygon[0].x == 0.1


@pytest.mark.parametrize(
    ("line_type", "position", "points", "direction"),
    [
        ("horizontal", None, None, "down"),
        ("vertical", 0.5, None, "down"),
        (
            "polygon",
            None,
            [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}],
            "right",
        ),
    ],
)
def test_invalid_virtual_line_geometry_is_rejected(
    line_type: str,
    position: float | None,
    points: list[dict] | None,
    direction: str,
) -> None:
    with pytest.raises(ValidationError):
        VirtualLineCreate(
            camera_id=uuid4(),
            line_key="transition-1",
            name="Transition 1",
            line_type=line_type,
            position=position,
            points=points,
            enter_direction=direction,
        )


def test_adjacency_rejects_self_route_and_invalid_time_window() -> None:
    zone_id = uuid4()
    with pytest.raises(ValidationError):
        ZoneAdjacencyCreate(
            source_zone_id=zone_id,
            target_zone_id=zone_id,
        )
    with pytest.raises(ValidationError):
        ZoneAdjacencyCreate(
            source_zone_id=uuid4(),
            target_zone_id=uuid4(),
            minimum_travel_seconds=30,
            maximum_travel_seconds=10,
        )


def test_camera_coverage_polygon_requires_three_points() -> None:
    with pytest.raises(ValidationError):
        CameraZoneMappingCreate(
            camera_id=uuid4(),
            zone_id=uuid4(),
            coverage_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}],
        )


def test_service_revalidates_merged_virtual_line_update() -> None:
    camera_id = uuid4()
    line = VirtualLine(
        id=uuid4(),
        camera_id=camera_id,
        line_key="gate",
        name="Gate",
        line_type=VirtualLineType.HORIZONTAL,
        position=0.5,
        points=None,
        enter_direction="down",
        enabled=True,
    )
    repository = SimpleNamespace(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        get_virtual_line=AsyncMock(return_value=line),
        find_virtual_line=AsyncMock(return_value=line),
    )
    service = TopologyService(repository)

    with pytest.raises(ValueError, match="direction"):
        asyncio.run(
            service.update_virtual_line(
                line.id,
                VirtualLineUpdate(enter_direction="left"),
                SimpleNamespace(id=uuid4()),
            )
        )


def test_service_blocks_line_for_camera_without_endpoint_coverage() -> None:
    repository = SimpleNamespace(
        session=SimpleNamespace(),
        get_zone=AsyncMock(
            return_value=Zone(
                id=uuid4(),
                building_id=uuid4(),
                code="ZONE",
                name="Zone",
                retention_days=90,
            )
        ),
        list_camera_mappings=AsyncMock(return_value=[]),
    )
    service = TopologyService(repository)

    with pytest.raises(TopologyValidationError, match="cover"):
        asyncio.run(
            service._validate_line_topology(uuid4(), uuid4(), None)
        )


def test_primary_virtual_line_keeps_legacy_runtime_payload_compatible() -> None:
    camera = Camera(id=uuid4(), name="CAM-01", rtsp_url="rtsp://example.test/stream")
    line = VirtualLine(
        id=uuid4(),
        camera_id=camera.id,
        line_key="mixing-entry",
        name="Mixing entry",
        line_type=VirtualLineType.VERTICAL,
        position=0.35,
        points=None,
        enter_direction="right",
        is_primary=True,
        enabled=True,
    )

    TopologyService._sync_legacy_crossing(camera, line)

    assert camera.crossing_config == {
        "enabled": True,
        "line_id": "mixing-entry",
        "line_type": "vertical",
        "position": 0.35,
        "enter_direction": "right",
        "polygon_points": [],
    }


def test_update_schema_distinguishes_omitted_and_explicit_null_fields() -> None:
    omitted = VirtualLineUpdate(name="Renamed")
    cleared = VirtualLineUpdate(from_zone_id=None)

    assert "from_zone_id" not in omitted.model_dump(exclude_unset=True)
    assert cleared.model_dump(exclude_unset=True)["from_zone_id"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"line_type": None},
        {"enabled": None},
    ],
)
def test_virtual_line_update_rejects_null_for_required_fields(payload: dict) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        VirtualLineUpdate(**payload)
