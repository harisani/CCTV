from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_camera_repository
from app.api.schemas import CameraCreate, CameraResponse, Page
from app.api.security import require_authenticated_user
from app.models import Camera
from app.repository import CameraRepository

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
    payload: CameraCreate, repository: CameraRepository = Depends(get_camera_repository)
) -> Camera:
    if await repository.get_by_name(payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Camera name already exists")
    camera = Camera(**payload.model_dump())
    try:
        await repository.add(camera)
        await repository.session.commit()
    except IntegrityError as error:
        await repository.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Camera could not be created") from error
    return camera


async def _delete_camera(camera_id: UUID, repository: CameraRepository) -> Response:
    camera = await repository.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await repository.session.delete(camera)
    await repository.session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: UUID = Query(), repository: CameraRepository = Depends(get_camera_repository)
) -> Response:
    return await _delete_camera(camera_id, repository)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def delete_camera_by_path(
    camera_id: UUID, repository: CameraRepository = Depends(get_camera_repository)
) -> Response:
    return await _delete_camera(camera_id, repository)
