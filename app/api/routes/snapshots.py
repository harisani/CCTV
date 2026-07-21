from uuid import UUID

from fastapi import APIRouter, Depends, Query
from app.api.dependencies import get_snapshot_repository
from app.api.schemas import Page, SnapshotResponse
from app.api.security import require_authenticated_user
from app.repository import SnapshotRepository

router = APIRouter(prefix="/snapshots", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[SnapshotResponse])
async def list_snapshots(
    camera_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: SnapshotRepository = Depends(get_snapshot_repository),
) -> Page[SnapshotResponse]:
    items, total = await repository.list_filtered(camera_id=camera_id, offset=offset, limit=limit)
    return Page[SnapshotResponse](items=items, total=total, offset=offset, limit=limit)
