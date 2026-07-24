"""Authenticated observation and administration of asynchronous AI jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_ai_job_service,
    get_database_session,
)
from app.api.processing_schemas import (
    AIProcessingJobDetailResponse,
    AIProcessingJobResponse,
    AIQueueStatisticsResponse,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user, require_roles
from app.models import (
    AIJobStatus,
    AIJobType,
    ProcessingPriority,
    User,
    UserRole,
)
from app.repository import AuditRepository
from app.services.ai_job_service import AIJobService

router = APIRouter(
    prefix="/processing-jobs",
    dependencies=[Depends(require_authenticated_user)],
)
admin_dependency = require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)


@router.get("", response_model=Page[AIProcessingJobResponse])
async def list_processing_jobs(
    job_status: AIJobStatus | None = Query(default=None, alias="status"),
    job_type: AIJobType | None = None,
    priority: ProcessingPriority | None = None,
    capture_event_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: AIJobService = Depends(get_ai_job_service),
) -> Page[AIProcessingJobResponse]:
    jobs, total = await service.list_jobs(
        status=job_status,
        job_type=job_type,
        priority=priority,
        capture_event_id=capture_event_id,
        offset=offset,
        limit=limit,
    )
    return Page[AIProcessingJobResponse](
        items=jobs,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/statistics", response_model=AIQueueStatisticsResponse)
async def processing_job_statistics(
    service: AIJobService = Depends(get_ai_job_service),
) -> AIQueueStatisticsResponse:
    return AIQueueStatisticsResponse.model_validate(
        await service.statistics()
    )


@router.get(
    "/{job_id}",
    response_model=AIProcessingJobDetailResponse,
)
async def get_processing_job(
    job_id: UUID,
    service: AIJobService = Depends(get_ai_job_service),
) -> AIProcessingJobDetailResponse:
    job = await service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return AIProcessingJobDetailResponse.model_validate(job)


@router.post(
    "/{job_id}/retry",
    response_model=AIProcessingJobResponse,
    dependencies=[Depends(admin_dependency)],
)
async def retry_processing_job(
    job_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    service: AIJobService = Depends(get_ai_job_service),
) -> AIProcessingJobResponse:
    try:
        job = await service.retry(job_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="AI_PROCESSING_JOB_RETRIED",
        resource_type="ai_processing_job",
        resource_id=str(job.id),
        details={"capture_event_id": str(job.capture_event_id)},
    )
    await session.commit()
    return AIProcessingJobResponse.model_validate(job)


@router.post(
    "/{job_id}/cancel",
    response_model=AIProcessingJobResponse,
    dependencies=[Depends(admin_dependency)],
)
async def cancel_processing_job(
    job_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    service: AIJobService = Depends(get_ai_job_service),
) -> AIProcessingJobResponse:
    try:
        job = await service.cancel(job_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="AI_PROCESSING_JOB_CANCELLED",
        resource_type="ai_processing_job",
        resource_id=str(job.id),
        details={"capture_event_id": str(job.capture_event_id)},
    )
    await session.commit()
    return AIProcessingJobResponse.model_validate(job)
