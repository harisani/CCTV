from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_camera_repository
from app.api.schemas import CameraConnectionResult, CameraConnectionTest, CameraCreate, CameraCrossingConfig, CameraResponse, CameraUpdate, Page
from app.api.security import require_authenticated_user, require_roles
from app.models import Camera, User, UserRole
from app.repository import AuditRepository, CameraRepository
from app.services.camera_connection_tester import CameraConnectionTester

router = APIRouter(prefix="/camera", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[CameraResponse])
async def list_cameras(
    search: str | None = Query(default=None, max_length=150),
    building: str | None = Query(default=None, max_length=100),
    floor: str | None = Query(default=None, max_length=50),
    zone: str | None = Query(default=None, max_length=100),
    camera_status: str | None = Query(default=None, alias="status", pattern="^(ONLINE|OFFLINE|RECONNECTING|ERROR)$"),
    enabled: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    repository: CameraRepository = Depends(get_camera_repository),
) -> Page[CameraResponse]:
    items, total = await repository.list_filtered(
        search=search,
        building=building,
        floor=floor,
        zone=zone,
        camera_status=camera_status,
        enabled=enabled,
        offset=offset,
        limit=limit,
    )
    return Page[CameraResponse](items=items, total=total, offset=offset, limit=limit)


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    repository: CameraRepository = Depends(get_camera_repository),
) -> Camera:
    if await repository.get_by_name(payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Camera name already exists")
    camera = Camera(**payload.model_dump())
    try:
        await repository.add(camera)
        await AuditRepository(repository.session).record(
            actor_user_id=actor.id,
            action="CAMERA_CREATED",
            resource_type="camera",
            resource_id=str(camera.id),
            details={"name": camera.name},
        )
        await repository.session.commit()
    except IntegrityError as error:
        await repository.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Camera could not be created") from error
    return camera


async def _delete_camera(camera_id: UUID, repository: CameraRepository, actor: User) -> Response:
    camera = await repository.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await AuditRepository(repository.session).record(
        actor_user_id=actor.id,
        action="CAMERA_ARCHIVED",
        resource_type="camera",
        resource_id=str(camera.id),
        details={"name": camera.name},
    )
    # Camera history is evidence and must not disappear with an operational action.
    # DELETE therefore removes the source from realtime processing without cascading
    # into Tracking/Event/Snapshot records. An administrator can enable it again.
    camera.enabled = False
    camera.status = "OFFLINE"
    camera.worker_id = None
    await repository.session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: UUID = Query(),
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    repository: CameraRepository = Depends(get_camera_repository),
) -> Response:
    return await _delete_camera(camera_id, repository, actor)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def delete_camera_by_path(
    camera_id: UUID,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    repository: CameraRepository = Depends(get_camera_repository),
) -> Response:
    return await _delete_camera(camera_id, repository, actor)


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    repository: CameraRepository = Depends(get_camera_repository),
) -> Camera:
    camera = await repository.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != camera.name and await repository.get_by_name(changes["name"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Camera name already exists")
    for field, value in changes.items():
        setattr(camera, field, value.strip() if isinstance(value, str) else value)
    await AuditRepository(repository.session).record(
        actor_user_id=actor.id,
        action="CAMERA_UPDATED",
        resource_type="camera",
        resource_id=str(camera.id),
        details={"fields": sorted(changes)},
    )
    await repository.session.commit()
    await repository.session.refresh(camera)
    return camera


@router.post("/test-connection", response_model=CameraConnectionResult)
async def test_camera_connection(
    payload: CameraConnectionTest,
    _: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> CameraConnectionResult:
    result = await CameraConnectionTester().test(payload.rtsp_url)
    return CameraConnectionResult(
        connected=result.connected,
        latency_ms=result.latency_ms,
        width=result.width,
        height=result.height,
        detail=result.detail,
    )


@router.get("/{camera_id}/crossing-config", response_model=CameraCrossingConfig | None)
async def get_crossing_config(
    camera_id: UUID,
    repository: CameraRepository = Depends(get_camera_repository),
) -> CameraCrossingConfig | None:
    camera = await repository.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return CameraCrossingConfig.model_validate(camera.crossing_config) if camera.crossing_config else None


@router.put("/{camera_id}/crossing-config", response_model=CameraCrossingConfig)
async def update_crossing_config(
    camera_id: UUID,
    payload: CameraCrossingConfig,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    repository: CameraRepository = Depends(get_camera_repository),
) -> CameraCrossingConfig:
    camera = await repository.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    camera.crossing_config = payload.model_dump(mode="json")
    await AuditRepository(repository.session).record(
        actor_user_id=actor.id,
        action="CAMERA_CROSSING_CONFIG_UPDATED",
        resource_type="camera",
        resource_id=str(camera.id),
        details={
            "line_id": payload.line_id,
            "line_type": payload.line_type,
            "enabled": payload.enabled,
        },
    )
    await repository.session.commit()
    return payload
