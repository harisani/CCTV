"""Observation endpoints for full-body ReID and PPE analysis."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.body_analysis_schemas import (
    BodyAnalysisConfigurationResponse,
    BodyCandidateResponse,
    BodyEmbeddingResponse,
    PPEAnalysisResponse,
)
from app.api.dependencies import (
    get_app_settings,
    get_body_analysis_service,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user
from app.config.settings import Settings
from app.models import PPEAnalysisStatus
from app.services.body_analysis_service import BodyAnalysisService

router = APIRouter(
    prefix="/body-analysis",
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/configuration", response_model=BodyAnalysisConfigurationResponse)
async def body_analysis_configuration(
    settings: Settings = Depends(get_app_settings),
) -> BodyAnalysisConfigurationResponse:
    return BodyAnalysisConfigurationResponse(
        realtime_reid_enabled=settings.enable_realtime_reid,
        body_similarity_threshold=settings.reid_similarity_threshold,
        body_ambiguity_margin=settings.reid_match_margin,
        body_minimum_quality=settings.reid_min_quality_score,
        body_embedding_retention_days=(
            settings.reid_embedding_retention_days
        ),
        ppe_analysis_enabled=settings.ppe_analysis_enabled,
        ppe_model_configured=bool(settings.ppe_model_path.strip()),
        ppe_confidence_threshold=settings.ppe_confidence_threshold,
    )


@router.get("/candidates", response_model=Page[BodyCandidateResponse])
async def list_body_candidates(
    capture_id: UUID | None = None,
    selected: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BodyAnalysisService = Depends(get_body_analysis_service),
) -> Page[BodyCandidateResponse]:
    items, total = await service.list_candidates(
        capture_id=capture_id,
        selected=selected,
        offset=offset,
        limit=limit,
    )
    return Page[BodyCandidateResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get("/embeddings", response_model=Page[BodyEmbeddingResponse])
async def list_body_embeddings(
    person_id: UUID | None = None,
    active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BodyAnalysisService = Depends(get_body_analysis_service),
) -> Page[BodyEmbeddingResponse]:
    items, total = await service.list_embeddings(
        person_id=person_id,
        active=active,
        offset=offset,
        limit=limit,
    )
    return Page[BodyEmbeddingResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get("/ppe", response_model=Page[PPEAnalysisResponse])
async def list_ppe_analyses(
    analysis_status: PPEAnalysisStatus | None = Query(
        default=None, alias="status"
    ),
    capture_id: UUID | None = None,
    needs_review: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BodyAnalysisService = Depends(get_body_analysis_service),
) -> Page[PPEAnalysisResponse]:
    items, total = await service.list_ppe(
        status=analysis_status,
        capture_id=capture_id,
        needs_review=needs_review,
        offset=offset,
        limit=limit,
    )
    return Page[PPEAnalysisResponse](
        items=items, total=total, offset=offset, limit=limit
    )
