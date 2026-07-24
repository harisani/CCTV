"""Policy administration and security alert workflow."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_policy_service
from app.api.policy_schemas import (
    AlertReviewRequest,
    PolicyEvaluationResponse,
    PolicyRuleCreate,
    PolicyRuleResponse,
    SecurityAlertResponse,
    SubjectPolicyProfileCreate,
    SubjectPolicyProfileResponse,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user, require_roles
from app.models import (
    SecurityAlertStatus,
    SecurityAlertType,
    User,
    UserRole,
)
from app.services.policy_service import PolicyService

router = APIRouter(
    prefix="/policies",
    dependencies=[Depends(require_authenticated_user)],
)
admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)
reviewer = require_roles(
    UserRole.SUPER_ADMIN, UserRole.ADMIN,
    UserRole.SUPERVISOR, UserRole.OPERATOR,
)


@router.get("/rules", response_model=list[PolicyRuleResponse])
async def list_policy_rules(
    service: PolicyService = Depends(get_policy_service),
) -> list:
    return await service.list_rules()


@router.post("/rules", response_model=PolicyRuleResponse, status_code=201)
async def create_policy_rule(
    payload: PolicyRuleCreate,
    actor: User = Depends(admin),
    service: PolicyService = Depends(get_policy_service),
) -> PolicyRuleResponse:
    try:
        return await service.create_rule(payload, actor)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/profiles", response_model=Page[SubjectPolicyProfileResponse]
)
async def list_subject_policy_profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    service: PolicyService = Depends(get_policy_service),
) -> Page[SubjectPolicyProfileResponse]:
    items, total = await service.list_profiles(offset=offset, limit=limit)
    return Page[SubjectPolicyProfileResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "/profiles",
    response_model=SubjectPolicyProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subject_policy_profile(
    payload: SubjectPolicyProfileCreate,
    actor: User = Depends(admin),
    service: PolicyService = Depends(get_policy_service),
) -> SubjectPolicyProfileResponse:
    try:
        return await service.create_profile(payload, actor)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/alerts", response_model=Page[SecurityAlertResponse])
async def list_security_alerts(
    alert_status: SecurityAlertStatus | None = Query(None, alias="status"),
    zone_id: UUID | None = None,
    alert_type: SecurityAlertType | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    service: PolicyService = Depends(get_policy_service),
):
    items, total = await service.list_alerts(
        status=alert_status, zone_id=zone_id, alert_type=alert_type,
        offset=offset, limit=limit,
    )
    return Page[SecurityAlertResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "/alerts/{alert_id}/review", response_model=SecurityAlertResponse
)
async def review_security_alert(
    alert_id: UUID,
    payload: AlertReviewRequest,
    actor: User = Depends(reviewer),
    service: PolicyService = Depends(get_policy_service),
) -> SecurityAlertResponse:
    try:
        return await service.review_alert(
            alert_id, action=payload.action, note=payload.note, actor=actor
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/evaluations", response_model=Page[PolicyEvaluationResponse]
)
async def list_policy_evaluations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    service: PolicyService = Depends(get_policy_service),
):
    items, total = await service.list_evaluations(
        offset=offset, limit=limit
    )
    return Page[PolicyEvaluationResponse](
        items=items, total=total, offset=offset, limit=limit
    )
