"""Policy configuration and security alert contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    PolicyEvaluationStatus,
    PolicyRuleType,
    SecurityAlertSeverity,
    SecurityAlertStatus,
    SecurityAlertType,
)


class PolicyRuleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    rule_type: PolicyRuleType
    zone_id: UUID | None = None
    severity: SecurityAlertSeverity = SecurityAlertSeverity.HIGH
    priority: int = Field(default=100, ge=0, le=10000)
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_configuration(self) -> "PolicyRuleCreate":
        list_keys = {
            PolicyRuleType.ZONE_AUTHORIZATION: (
                "allowed_person_ids",
                "allowed_external_subject_keys",
            ),
            PolicyRuleType.DIVISION_PERMISSION: ("allowed_departments",),
            PolicyRuleType.PPE_COLOR: ("allowed_colors",),
            PolicyRuleType.PPE_COMPLETENESS: ("required_items",),
        }
        for key in list_keys.get(self.rule_type, ()):
            value = self.configuration.get(key, [])
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(f"configuration.{key} must be a string list")
        if self.rule_type == PolicyRuleType.ZONE_AUTHORIZATION:
            try:
                for value in self.configuration.get(
                    "allowed_person_ids", []
                ):
                    UUID(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "configuration.allowed_person_ids must contain UUIDs"
                ) from error
        if self.rule_type == PolicyRuleType.PROCESSING_DELAY:
            threshold = self.configuration.get("threshold_seconds")
            if (
                threshold is not None
                and (
                    not isinstance(threshold, (int, float))
                    or isinstance(threshold, bool)
                    or threshold <= 0
                )
            ):
                raise ValueError(
                    "configuration.threshold_seconds must be positive"
                )
        return self


class PolicyRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    rule_type: PolicyRuleType
    zone_id: UUID | None
    severity: SecurityAlertSeverity
    priority: int
    configuration: dict[str, Any]
    enabled: bool
    created_at: datetime


class SecurityAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    alert_type: SecurityAlertType
    severity: SecurityAlertSeverity
    status: SecurityAlertStatus
    policy_rule_id: UUID | None
    zone_id: UUID | None
    camera_id: UUID | None
    journey_id: UUID | None
    occupancy_session_id: UUID | None
    capture_event_id: UUID | None
    person_id: UUID | None
    external_subject_key: str | None
    title: str
    description: str
    evidence: dict[str, Any]
    occurred_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by_user_id: UUID | None
    resolution_note: str | None


class AlertReviewRequest(BaseModel):
    action: Literal["ACKNOWLEDGED", "RESOLVED", "DISMISSED"]
    note: str = Field(min_length=3, max_length=2000)


class PolicyEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    occupancy_fact_id: UUID
    capture_event_id: UUID
    status: PolicyEvaluationStatus
    evaluated_rule_count: int
    alert_count: int
    decisions: list[dict[str, Any]]
    evaluated_at: datetime


class SubjectPolicyProfileCreate(BaseModel):
    person_id: UUID | None = None
    external_subject_key: str | None = Field(
        default=None, min_length=1, max_length=160
    )
    employee_key: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    department_code: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    active: bool = True
    profile_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_subject(self) -> "SubjectPolicyProfileCreate":
        if self.person_id is None and self.external_subject_key is None:
            raise ValueError(
                "person_id or external_subject_key must be provided"
            )
        return self


class SubjectPolicyProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    person_id: UUID | None
    external_subject_key: str | None
    employee_key: str | None
    department_code: str | None
    active: bool
    profile_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
