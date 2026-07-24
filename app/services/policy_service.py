"""Fail-safe policy evaluation and auditable security alert workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.models import (
    AuditLog,
    IdentityDecision,
    JourneyCorrelationDecision,
    OccupancyFact,
    OccupancyFactType,
    OccupancySubjectType,
    PolicyEvaluation,
    PolicyEvaluationStatus,
    PolicyRule,
    PolicyRuleType,
    PPEAnalysisStatus,
    SecurityAlert,
    SecurityAlertSeverity,
    SecurityAlertStatus,
    SecurityAlertType,
    SubjectPolicyProfile,
    User,
    ZoneSensitivity,
)
from app.repository import PolicyRepository


@dataclass(frozen=True, slots=True)
class AlertDecision:
    alert_type: SecurityAlertType
    severity: SecurityAlertSeverity
    title: str
    description: str
    rule_id: UUID | None = None
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PolicyResult:
    evaluation: PolicyEvaluation
    alerts: list[SecurityAlert]
    needs_review: bool


class PolicyEvaluator:
    def __init__(
        self, processing_delay_threshold_seconds: float = 120.0
    ) -> None:
        self.processing_delay_threshold_seconds = (
            processing_delay_threshold_seconds
        )

    def evaluate(
        self,
        *,
        fact: OccupancyFact,
        zone: Any,
        camera: Any,
        profile: Any,
        ppe: Any,
        rules: list[PolicyRule],
        processing_delay_seconds: float,
    ) -> tuple[list[AlertDecision], list[dict[str, Any]], bool]:
        alerts: list[AlertDecision] = []
        decisions: list[dict[str, Any]] = []
        inconclusive = False
        configurable_baselines = {
            PolicyRuleType.UNKNOWN_PERSON,
            PolicyRuleType.UNRESOLVED_PERSON,
            PolicyRuleType.CAMERA_OFFLINE,
            PolicyRuleType.PROCESSING_DELAY,
            PolicyRuleType.IDENTITY_CONFLICT,
        }
        baseline_rules = {
            rule.rule_type: rule
            for rule in rules
            if rule.rule_type in configurable_baselines
        }

        def add_baseline(
            *,
            condition: bool,
            rule_type: PolicyRuleType | None,
            alert_type: SecurityAlertType,
            severity: SecurityAlertSeverity,
            title: str,
            description: str,
        ) -> None:
            rule = baseline_rules.get(rule_type) if rule_type else None
            if rule is not None:
                decisions.append({
                    "rule_id": str(rule.id),
                    "rule_type": rule.rule_type.value,
                    "outcome": "VIOLATION" if condition else "PASS",
                })
            if not condition:
                return
            if rule is not None:
                alerts.append(self._rule_alert(rule, alert_type, description))
            else:
                alerts.append(AlertDecision(
                    alert_type, severity, title, description
                ))

        unknown_entry = (
            fact.subject_type == OccupancySubjectType.UNKNOWN
            and fact.fact_type
            in (OccupancyFactType.ENTER, OccupancyFactType.TRANSITION)
        )
        unknown_active = (
            fact.subject_type == OccupancySubjectType.UNKNOWN
            and fact.fact_type == OccupancyFactType.OBSERVATION
        )
        if unknown_entry or unknown_active:
            kind = (
                SecurityAlertType.UNKNOWN_ENTER
                if unknown_entry
                else SecurityAlertType.UNKNOWN_ACTIVE
            )
            add_baseline(
                condition=True,
                rule_type=PolicyRuleType.UNKNOWN_PERSON,
                alert_type=kind,
                severity=SecurityAlertSeverity.HIGH,
                title="Unknown person in monitored zone",
                description="Identity remains unknown after correlation.",
            )
        elif PolicyRuleType.UNKNOWN_PERSON in baseline_rules:
            add_baseline(
                condition=False,
                rule_type=PolicyRuleType.UNKNOWN_PERSON,
                alert_type=SecurityAlertType.UNKNOWN_ACTIVE,
                severity=SecurityAlertSeverity.HIGH,
                title="Unknown person in monitored zone",
                description="Identity remains unknown after correlation.",
            )
        add_baseline(
            condition=(
                fact.subject_type == OccupancySubjectType.UNRESOLVED
            ),
            rule_type=PolicyRuleType.UNRESOLVED_PERSON,
            alert_type=SecurityAlertType.UNRESOLVED_IDENTITY,
            severity=SecurityAlertSeverity.HIGH,
            title="Identity could not be resolved",
            description=(
                "Available biometric evidence was insufficient or conflicting."
            ),
        )
        add_baseline(
            condition=fact.identity_decision == IdentityDecision.CONFLICT,
            rule_type=PolicyRuleType.IDENTITY_CONFLICT,
            alert_type=SecurityAlertType.IDENTITY_CONFLICT,
            severity=SecurityAlertSeverity.HIGH,
            title="Identity evidence conflict",
            description="Face/body identity signals disagree.",
        )
        add_baseline(
            condition=(
                fact.correlation_decision
                == JourneyCorrelationDecision.IMPOSSIBLE_TRAVEL
            ),
            rule_type=None,
            alert_type=SecurityAlertType.IMPOSSIBLE_TRAVEL,
            severity=SecurityAlertSeverity.CRITICAL,
            title="Physically impossible travel",
            description="Journey topology or travel time rejected the merge.",
        )
        add_baseline(
            condition=(
                fact.correlation_decision
                == JourneyCorrelationDecision.AMBIGUOUS
            ),
            rule_type=None,
            alert_type=SecurityAlertType.DUPLICATE_JOURNEY,
            severity=SecurityAlertSeverity.MEDIUM,
            title="Ambiguous journey correlation",
            description="Multiple journey candidates had similar scores.",
        )
        add_baseline(
            condition=camera is not None and camera.status != "ONLINE",
            rule_type=PolicyRuleType.CAMERA_OFFLINE,
            alert_type=SecurityAlertType.CAMERA_OFFLINE,
            severity=SecurityAlertSeverity.HIGH,
            title="Camera offline during policy evaluation",
            description="Camera health is not ONLINE.",
        )
        delay_rule = baseline_rules.get(PolicyRuleType.PROCESSING_DELAY)
        delay_threshold = self.processing_delay_threshold_seconds
        if delay_rule is not None:
            delay_threshold = float(
                (delay_rule.configuration or {}).get(
                    "threshold_seconds", delay_threshold
                )
            )
        add_baseline(
            condition=processing_delay_seconds > delay_threshold,
            rule_type=PolicyRuleType.PROCESSING_DELAY,
            alert_type=SecurityAlertType.PROCESSING_BACKLOG,
            severity=SecurityAlertSeverity.MEDIUM,
            title="Processing delay exceeded baseline",
            description=(
                f"Capture processing delay is {processing_delay_seconds:.1f}s; "
                f"threshold is {delay_threshold:.1f}s."
            ),
        )

        for rule in rules:
            if rule.rule_type in configurable_baselines:
                continue
            cfg = rule.configuration or {}
            outcome = "PASS"
            if (
                fact.fact_type == OccupancyFactType.EXIT
                and rule.rule_type
                in {
                    PolicyRuleType.ZONE_AUTHORIZATION,
                    PolicyRuleType.DIVISION_PERMISSION,
                    PolicyRuleType.RESTRICTED_ZONE,
                }
            ):
                decisions.append({
                    "rule_id": str(rule.id),
                    "rule_type": rule.rule_type.value,
                    "outcome": "NOT_APPLICABLE",
                })
                continue
            if rule.rule_type == PolicyRuleType.ZONE_AUTHORIZATION:
                allowed_people = set(cfg.get("allowed_person_ids", []))
                allowed_external = set(cfg.get("allowed_external_subject_keys", []))
                allowed = (
                    (fact.person_id and str(fact.person_id) in allowed_people)
                    or (
                        fact.external_subject_key
                        and fact.external_subject_key in allowed_external
                    )
                )
                if not allowed:
                    outcome = "VIOLATION"
                    alerts.append(self._rule_alert(
                        rule, SecurityAlertType.UNAUTHORIZED_ZONE_ENTRY,
                        "Subject is not authorized for this zone",
                    ))
            elif rule.rule_type == PolicyRuleType.DIVISION_PERMISSION:
                allowed = set(cfg.get("allowed_departments", []))
                if profile is None or not profile.department_code:
                    outcome, inconclusive = "INCONCLUSIVE", True
                elif profile.department_code not in allowed:
                    outcome = "VIOLATION"
                    alerts.append(self._rule_alert(
                        rule, SecurityAlertType.UNAUTHORIZED_ZONE_ENTRY,
                        "Department is not permitted in this zone",
                    ))
            elif rule.rule_type == PolicyRuleType.PPE_COLOR:
                color = (
                    (ppe.color_observation or {}).get("dominant_color")
                    if ppe else None
                )
                if not color:
                    outcome, inconclusive = "INCONCLUSIVE", True
                elif color not in set(cfg.get("allowed_colors", [])):
                    outcome = "VIOLATION"
                    alerts.append(self._rule_alert(
                        rule, SecurityAlertType.PPE_MISMATCH,
                        "Observed APD color is not allowed",
                    ))
            elif rule.rule_type == PolicyRuleType.PPE_COMPLETENESS:
                if ppe is None or ppe.status == PPEAnalysisStatus.MODEL_UNAVAILABLE:
                    outcome, inconclusive = "INCONCLUSIVE", True
                else:
                    required = set(cfg.get("required_items", []))
                    missing = [
                        item for item in required
                        if (ppe.observed_items or {}).get(item, {}).get("state")
                        == "MISSING"
                    ]
                    if missing:
                        outcome = "VIOLATION"
                        alerts.append(self._rule_alert(
                            rule, SecurityAlertType.PPE_INCOMPLETE,
                            f"Explicit missing APD: {', '.join(sorted(missing))}",
                        ))
                    elif any(item not in (ppe.observed_items or {}) for item in required):
                        outcome, inconclusive = "INCONCLUSIVE", True
            elif rule.rule_type == PolicyRuleType.RESTRICTED_ZONE:
                if (
                    zone
                    and zone.sensitivity
                    in (ZoneSensitivity.RESTRICTED, ZoneSensitivity.CRITICAL)
                    and fact.subject_type != OccupancySubjectType.EMPLOYEE
                ):
                    outcome = "VIOLATION"
                    alerts.append(self._rule_alert(
                        rule,
                        SecurityAlertType.UNAUTHORIZED_ZONE_ENTRY,
                        "Non-employee subject entered a restricted zone",
                    ))
            decisions.append({
                "rule_id": str(rule.id),
                "rule_type": rule.rule_type.value,
                "outcome": outcome,
            })
        return alerts, decisions, inconclusive

    @staticmethod
    def _rule_alert(
        rule: PolicyRule, alert_type: SecurityAlertType, description: str
    ) -> AlertDecision:
        return AlertDecision(
            alert_type, rule.severity, rule.name, description, rule.id,
            {"rule_configuration_version": rule.updated_at.isoformat() if rule.updated_at else None},
        )


class PolicyService:
    def __init__(self, repository: PolicyRepository, settings: Any) -> None:
        self.repository = repository
        self.settings = settings
        self.evaluator = PolicyEvaluator(
            settings.policy_processing_delay_seconds
        )

    async def create_rule(
        self, payload: Any, actor: User
    ) -> PolicyRule:
        if await self.repository.rule_name_exists(payload.name):
            raise ValueError("Policy rule name already exists")
        rule = PolicyRule(
            id=uuid4(),
            **payload.model_dump(),
            created_by_user_id=actor.id,
        )
        self.repository.add(rule)
        self.repository.add(AuditLog(
            actor_user_id=actor.id, action="POLICY_RULE_CREATED",
            resource_type="policy_rule", resource_id=str(rule.id),
            details={"name": rule.name, "rule_type": rule.rule_type.value},
        ))
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ValueError("Policy rule conflicts with existing data") from error
        return rule

    async def list_rules(self) -> list[PolicyRule]:
        return await self.repository.list_rules()

    async def list_alerts(self, **filters: Any) -> Any:
        return await self.repository.list_alerts(**filters)

    async def list_evaluations(self, **filters: Any) -> Any:
        return await self.repository.list_evaluations(**filters)

    async def create_profile(
        self, payload: Any, actor: User
    ) -> SubjectPolicyProfile:
        values = payload.model_dump()
        if await self.repository.profile_exists(
            values["person_id"], values["external_subject_key"]
        ):
            raise ValueError("Subject policy profile already exists")
        profile = SubjectPolicyProfile(id=uuid4(), **values)
        self.repository.add(profile)
        self.repository.add(AuditLog(
            actor_user_id=actor.id,
            action="SUBJECT_POLICY_PROFILE_CREATED",
            resource_type="subject_policy_profile",
            resource_id=str(profile.id),
            details={
                "person_id": (
                    str(profile.person_id) if profile.person_id else None
                ),
                "external_subject_key": profile.external_subject_key,
            },
        ))
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ValueError(
                "Subject policy profile conflicts with existing data"
            ) from error
        return profile

    async def list_profiles(self, **filters: Any) -> Any:
        return await self.repository.list_profiles(**filters)

    async def evaluate_capture(self, capture_id: UUID) -> PolicyResult:
        fact = await self.repository.fact_for_capture(capture_id)
        capture = await self.repository.capture(capture_id)
        if fact is None or capture is None:
            raise LookupError("Occupancy fact or capture not found")
        existing = await self.repository.evaluation(fact.id)
        if existing:
            return PolicyResult(existing, [], existing.alert_count > 0)
        zone = await self.repository.zone(fact.current_zone_id or fact.origin_zone_id)
        camera = await self.repository.camera(fact.camera_id)
        profile = await self.repository.profile(fact.person_id, fact.external_subject_key)
        ppe = await self.repository.ppe(capture_id)
        occupancy_session = await self.repository.session_for_fact(fact)
        rules = await self.repository.rules(zone.id if zone else None)
        delay = max(0.0, (datetime.now(UTC) - capture.captured_at).total_seconds())
        proposed, decisions, inconclusive = self.evaluator.evaluate(
            fact=fact, zone=zone, camera=camera, profile=profile, ppe=ppe,
            rules=rules, processing_delay_seconds=delay,
        )
        alerts: list[SecurityAlert] = []
        for item in proposed:
            key = f"policy:{fact.id}:{item.alert_type.value}:{item.rule_id or 'baseline'}"
            alert = await self.repository.alert_by_key(key)
            if alert is None:
                alert = SecurityAlert(
                    id=uuid4(), deduplication_key=key,
                    alert_type=item.alert_type, severity=item.severity,
                    status=SecurityAlertStatus.OPEN,
                    policy_rule_id=item.rule_id,
                    zone_id=fact.current_zone_id or fact.origin_zone_id,
                    camera_id=fact.camera_id, journey_id=fact.journey_id,
                    occupancy_session_id=(
                        occupancy_session.id if occupancy_session else None
                    ),
                    capture_event_id=capture_id,
                    person_id=fact.person_id,
                    external_subject_key=fact.external_subject_key,
                    title=item.title, description=item.description,
                    evidence={
                        **(item.evidence or {}),
                        "occupancy_fact_id": str(fact.id),
                        "journey_event_id": str(fact.journey_event_id),
                        "identity_confidence": fact.identity_confidence,
                        "correlation_score": fact.correlation_score,
                    },
                    occurred_at=fact.occurred_at,
                )
                self.repository.add(alert)
            alerts.append(alert)
        evaluation = PolicyEvaluation(
            id=uuid4(), idempotency_key=f"policy-evaluation:{fact.id}",
            occupancy_fact_id=fact.id, capture_event_id=capture_id,
            status=(
                PolicyEvaluationStatus.INCONCLUSIVE
                if inconclusive else PolicyEvaluationStatus.COMPLETED
            ),
            evaluated_rule_count=len(rules), alert_count=len(alerts),
            decisions=decisions, evaluated_at=datetime.now(UTC),
        )
        self.repository.add(evaluation)
        await self.repository.commit()
        return PolicyResult(evaluation, alerts, bool(alerts))

    async def review_alert(
        self, alert_id: UUID, *, action: str, note: str, actor: User
    ) -> SecurityAlert:
        alert = await self.repository.get_alert(alert_id)
        if alert is None:
            raise LookupError("Security alert not found")
        if alert.status in (
            SecurityAlertStatus.RESOLVED,
            SecurityAlertStatus.DISMISSED,
        ):
            raise ValueError("A closed security alert cannot be reviewed again")
        target = SecurityAlertStatus(action)
        if (
            target == SecurityAlertStatus.ACKNOWLEDGED
            and alert.status != SecurityAlertStatus.OPEN
        ):
            raise ValueError("Only an open alert can be acknowledged")
        now = datetime.now(UTC)
        alert.status = target
        if alert.status == SecurityAlertStatus.ACKNOWLEDGED:
            alert.acknowledged_at = now
        else:
            alert.reviewed_at = now
        alert.reviewed_by_user_id = actor.id
        alert.resolution_note = note
        self.repository.add(AuditLog(
            actor_user_id=actor.id, action=f"SECURITY_ALERT_{action}",
            resource_type="security_alert", resource_id=str(alert.id),
            details={"note": note},
        ))
        await self.repository.commit()
        return alert


class OperationalSecurityAlertService:
    """Create and auto-resolve infrastructure alerts on health transitions."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def camera_health_changed(
        self,
        camera_id: UUID,
        *,
        status: str,
        occurred_at: datetime,
        reason: str | None,
    ) -> None:
        if status not in {"ONLINE", "OFFLINE"}:
            return
        async with self.session_factory() as session:
            repository = PolicyRepository(session)
            existing = await repository.active_camera_alert(camera_id)
            if status == "ONLINE":
                if existing is None:
                    return
                existing.status = SecurityAlertStatus.RESOLVED
                existing.reviewed_at = occurred_at
                existing.resolution_note = (
                    "Camera stream recovered automatically."
                )
                repository.add(AuditLog(
                    actor_user_id=None,
                    action="CAMERA_OFFLINE_ALERT_AUTO_RESOLVED",
                    resource_type="security_alert",
                    resource_id=str(existing.id),
                    details={"camera_id": str(camera_id)},
                ))
                await repository.commit()
                return
            if existing is not None:
                return
            alert = SecurityAlert(
                id=uuid4(),
                deduplication_key=(
                    f"camera-offline:{camera_id}:{occurred_at.isoformat()}"
                ),
                alert_type=SecurityAlertType.CAMERA_OFFLINE,
                severity=SecurityAlertSeverity.HIGH,
                status=SecurityAlertStatus.OPEN,
                camera_id=camera_id,
                title="Camera stream offline",
                description=(
                    reason
                    or "No fresh frame is available from the camera."
                ),
                evidence={
                    "camera_id": str(camera_id),
                    "reported_status": status,
                    "reason": reason,
                },
                occurred_at=occurred_at,
            )
            repository.add(alert)
            repository.add(AuditLog(
                actor_user_id=None,
                action="CAMERA_OFFLINE_ALERT_CREATED",
                resource_type="security_alert",
                resource_id=str(alert.id),
                details={"camera_id": str(camera_id)},
            ))
            await repository.commit()
