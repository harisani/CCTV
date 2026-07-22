from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database_session, get_person_repository
from app.api.schemas import (
    Page,
    PersonMergeRequest,
    PersonResponse,
    PersonSplitRequest,
    PersonTrackingResponse,
    ReIdConfigurationResponse,
)
from app.api.security import require_authenticated_user, require_roles
from app.config.settings import Settings
from app.models import Person, User, UserRole
from app.repository import PersonRepository
from app.services.person_identity_service import PersonIdentityService

router = APIRouter(prefix="/persons", dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=Page[PersonResponse])
async def list_persons(
    name: str | None = Query(default=None, max_length=100),
    include_merged: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: PersonRepository = Depends(get_person_repository),
) -> Page[PersonResponse]:
    items, total = await repository.list_filtered(
        name=name, offset=offset, limit=limit, include_merged=include_merged
    )
    return Page[PersonResponse](items=items, total=total, offset=offset, limit=limit)


@router.get("/reid-config", response_model=ReIdConfigurationResponse)
async def get_reid_configuration(
    settings: Settings = Depends(get_app_settings),
) -> ReIdConfigurationResponse:
    return ReIdConfigurationResponse(
        similarity_threshold=settings.reid_similarity_threshold,
        ambiguity_margin=settings.reid_match_margin,
        minimum_quality=settings.reid_min_quality_score,
        retention_days=settings.reid_embedding_retention_days,
        minimum_templates_per_person=settings.reid_min_embeddings_per_person,
        maximum_templates_per_person=settings.reid_max_embeddings_per_person,
    )


@router.get("/{person_id}/trackings", response_model=list[PersonTrackingResponse])
async def get_person_trackings(
    person_id: UUID,
    session: AsyncSession = Depends(get_database_session),
) -> list[dict]:
    return await PersonIdentityService(session).tracking_history(person_id)


@router.post("/merge", response_model=PersonResponse)
async def merge_person_identities(
    payload: PersonMergeRequest,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_database_session),
) -> Person:
    return await PersonIdentityService(session).merge(
        target_id=payload.target_person_id,
        source_ids=payload.source_person_ids,
        actor=actor,
    )


@router.post("/{person_id}/split", response_model=PersonResponse)
async def split_person_identity(
    person_id: UUID,
    payload: PersonSplitRequest,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_database_session),
) -> Person:
    return await PersonIdentityService(session).split(
        source_id=person_id,
        tracking_ids=payload.tracking_ids,
        display_name=payload.display_name,
        actor=actor,
    )
