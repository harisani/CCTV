"""Authenticated biometric enrollment and identity-decision endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.biometric_schemas import (
    BiometricEnrollmentRequest,
    BiometricTemplateResponse,
    FaceCandidateResponse,
    IdentityMatchResponse,
)
from app.api.dependencies import (
    get_biometric_identity_service,
    get_database_session,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user, require_roles
from app.models import (
    IdentityDecision,
    IdentityReviewStatus,
    User,
    UserRole,
)
from app.repository import AuditRepository
from app.services.biometric_identity_service import BiometricIdentityService

router = APIRouter(
    prefix="/biometrics",
    dependencies=[Depends(require_authenticated_user)],
)
admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)


@router.get(
    "/captures/{capture_id}/candidates",
    response_model=list[FaceCandidateResponse],
)
async def list_face_candidates(
    capture_id: UUID,
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> list[FaceCandidateResponse]:
    candidates = await service.list_candidates(capture_id)
    if candidates is None:
        raise HTTPException(404, "Capture event not found")
    return [
        FaceCandidateResponse.model_validate(candidate)
        for candidate in candidates
    ]


@router.get("/matches", response_model=Page[IdentityMatchResponse])
async def list_identity_matches(
    decision: IdentityDecision | None = None,
    review_status: IdentityReviewStatus | None = None,
    capture_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> Page[IdentityMatchResponse]:
    items, total = await service.list_matches(
        decision=decision,
        review_status=review_status,
        capture_id=capture_id,
        offset=offset,
        limit=limit,
    )
    return Page[IdentityMatchResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.get(
    "/matches/{match_id}",
    response_model=IdentityMatchResponse,
)
async def get_identity_match(
    match_id: UUID,
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> IdentityMatchResponse:
    match = await service.get_match(match_id)
    if match is None:
        raise HTTPException(404, "Identity match not found")
    return IdentityMatchResponse.model_validate(match)


@router.get(
    "/templates",
    response_model=Page[BiometricTemplateResponse],
    dependencies=[Depends(admin)],
)
async def list_biometric_templates(
    active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> Page[BiometricTemplateResponse]:
    items, total = await service.list_templates(
        active=active, offset=offset, limit=limit
    )
    return Page[BiometricTemplateResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "/templates",
    response_model=BiometricTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin)],
)
async def enroll_biometric_template(
    payload: BiometricEnrollmentRequest,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> BiometricTemplateResponse:
    try:
        template = await service.enroll(
            source_asset_id=payload.source_asset_id,
            person_id=payload.person_id,
            external_subject_key=payload.external_subject_key,
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="BIOMETRIC_TEMPLATE_ENROLLED",
        resource_type="biometric_template",
        resource_id=str(template.id),
        details={
            "person_id": str(template.person_id)
            if template.person_id
            else None,
            "external_subject_key": template.external_subject_key,
            "source_asset_id": str(payload.source_asset_id),
        },
    )
    await session.commit()
    return BiometricTemplateResponse.model_validate(template)


@router.delete(
    "/templates/{template_id}",
    response_model=BiometricTemplateResponse,
    dependencies=[Depends(admin)],
)
async def revoke_biometric_template(
    template_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    service: BiometricIdentityService = Depends(
        get_biometric_identity_service
    ),
) -> BiometricTemplateResponse:
    template = await service.revoke_template(template_id)
    if template is None:
        raise HTTPException(404, "Biometric template not found")
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="BIOMETRIC_TEMPLATE_REVOKED",
        resource_type="biometric_template",
        resource_id=str(template.id),
    )
    await session.commit()
    return BiometricTemplateResponse.model_validate(template)
