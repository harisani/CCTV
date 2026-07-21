from fastapi import APIRouter, Depends, Query
from app.api.dependencies import get_person_repository
from app.api.schemas import Page, PersonResponse
from app.api.security import require_authenticated_user
from app.repository import PersonRepository

router = APIRouter(prefix="/persons", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[PersonResponse])
async def list_persons(
    name: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: PersonRepository = Depends(get_person_repository),
) -> Page[PersonResponse]:
    items, total = await repository.list_filtered(name=name, offset=offset, limit=limit)
    return Page[PersonResponse](items=items, total=total, offset=offset, limit=limit)
