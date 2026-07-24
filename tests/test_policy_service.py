import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.policy_schemas import PolicyRuleCreate
from app.models import (
    IdentityDecision,
    JourneyCorrelationDecision,
    OccupancyFactType,
    OccupancySubjectType,
    PolicyRule,
    PolicyRuleType,
    PPEAnalysisStatus,
    SecurityAlertSeverity,
    SecurityAlertStatus,
    SecurityAlertType,
    ZoneSensitivity,
)
from app.services.policy_service import (
    OperationalSecurityAlertService,
    PolicyEvaluator,
    PolicyService,
)


def fact(**overrides):
    values = {
        "subject_type": OccupancySubjectType.EMPLOYEE,
        "fact_type": OccupancyFactType.ENTER,
        "person_id": uuid4(),
        "external_subject_key": None,
        "identity_decision": IdentityDecision.CONFIRMED,
        "correlation_decision": JourneyCorrelationDecision.MATCHED,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def rule(rule_type, configuration=None, severity=SecurityAlertSeverity.HIGH):
    return PolicyRule(
        id=uuid4(),
        name=f"{rule_type.value}-{uuid4()}",
        rule_type=rule_type,
        zone_id=None,
        severity=severity,
        priority=100,
        configuration=configuration or {},
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def evaluate(subject, *, rules=None, ppe=None, zone=None, delay=0):
    return PolicyEvaluator(120).evaluate(
        fact=subject,
        zone=zone,
        camera=SimpleNamespace(status="ONLINE"),
        profile=None,
        ppe=ppe,
        rules=rules or [],
        processing_delay_seconds=delay,
    )


def test_unknown_entry_alerts_but_unknown_exit_does_not():
    enter_alerts, _, _ = evaluate(fact(
        subject_type=OccupancySubjectType.UNKNOWN,
        person_id=None,
        identity_decision=IdentityDecision.UNKNOWN,
    ))
    exit_alerts, _, _ = evaluate(fact(
        subject_type=OccupancySubjectType.UNKNOWN,
        fact_type=OccupancyFactType.EXIT,
        person_id=None,
        identity_decision=IdentityDecision.UNKNOWN,
    ))

    assert [item.alert_type for item in enter_alerts] == [
        SecurityAlertType.UNKNOWN_ENTER
    ]
    assert exit_alerts == []


def test_ppe_missing_requires_explicit_missing_observation():
    ppe_rule = rule(
        PolicyRuleType.PPE_COMPLETENESS,
        {"required_items": ["HELMET", "VEST"]},
    )
    ppe = SimpleNamespace(
        status=PPEAnalysisStatus.COMPLETED,
        observed_items={
            "HELMET": {"state": "MISSING", "confidence": 0.94}
        },
    )

    alerts, decisions, inconclusive = evaluate(
        fact(), rules=[ppe_rule], ppe=ppe
    )

    assert [item.alert_type for item in alerts] == [
        SecurityAlertType.PPE_INCOMPLETE
    ]
    assert decisions[0]["outcome"] == "VIOLATION"
    assert inconclusive is False


def test_ppe_model_unavailable_is_inconclusive_not_violation():
    ppe_rule = rule(
        PolicyRuleType.PPE_COMPLETENESS,
        {"required_items": ["HELMET"]},
    )
    ppe = SimpleNamespace(
        status=PPEAnalysisStatus.MODEL_UNAVAILABLE,
        observed_items={},
    )

    alerts, decisions, inconclusive = evaluate(
        fact(), rules=[ppe_rule], ppe=ppe
    )

    assert alerts == []
    assert decisions[0]["outcome"] == "INCONCLUSIVE"
    assert inconclusive is True


def test_restricted_zone_rule_creates_security_alert():
    restricted = rule(PolicyRuleType.RESTRICTED_ZONE)
    zone = SimpleNamespace(sensitivity=ZoneSensitivity.CRITICAL)

    alerts, decisions, _ = evaluate(
        fact(
            subject_type=OccupancySubjectType.UNKNOWN,
            person_id=None,
            identity_decision=IdentityDecision.UNKNOWN,
        ),
        rules=[restricted],
        zone=zone,
    )

    assert SecurityAlertType.UNAUTHORIZED_ZONE_ENTRY in {
        item.alert_type for item in alerts
    }
    assert decisions[-1]["outcome"] == "VIOLATION"


def test_access_rule_does_not_create_entry_alert_on_exit():
    authorization = rule(
        PolicyRuleType.ZONE_AUTHORIZATION,
        {"allowed_person_ids": [], "allowed_external_subject_keys": []},
    )

    alerts, decisions, _ = evaluate(
        fact(fact_type=OccupancyFactType.EXIT),
        rules=[authorization],
    )

    assert alerts == []
    assert decisions[0]["outcome"] == "NOT_APPLICABLE"


def test_processing_delay_rule_overrides_threshold_and_severity():
    delay_rule = rule(
        PolicyRuleType.PROCESSING_DELAY,
        {"threshold_seconds": 10},
        SecurityAlertSeverity.CRITICAL,
    )

    alerts, decisions, _ = evaluate(
        fact(), rules=[delay_rule], delay=11
    )

    assert alerts[0].alert_type == SecurityAlertType.PROCESSING_BACKLOG
    assert alerts[0].severity == SecurityAlertSeverity.CRITICAL
    assert alerts[0].rule_id == delay_rule.id
    assert decisions[0]["outcome"] == "VIOLATION"


def test_policy_schema_rejects_invalid_processing_threshold():
    with pytest.raises(ValidationError):
        PolicyRuleCreate(
            name="Invalid delay",
            rule_type=PolicyRuleType.PROCESSING_DELAY,
            configuration={"threshold_seconds": -1},
        )


class ReviewRepository:
    def __init__(self, alert):
        self.alert = alert
        self.added = []
        self.committed = False

    async def get_alert(self, _alert_id):
        return self.alert

    def add(self, entity):
        self.added.append(entity)

    async def commit(self):
        self.committed = True


def test_closed_alert_cannot_be_reviewed_again():
    alert = SimpleNamespace(status=SecurityAlertStatus.RESOLVED)
    repository = ReviewRepository(alert)
    service = PolicyService(
        repository,
        SimpleNamespace(policy_processing_delay_seconds=120),
    )

    async def exercise():
        with pytest.raises(ValueError, match="closed"):
            await service.review_alert(
                uuid4(),
                action="DISMISSED",
                note="Duplicate observation",
                actor=SimpleNamespace(id=uuid4()),
            )

    asyncio.run(exercise())

    assert repository.committed is False


class OperationalRepository:
    alert = None
    added = []
    commits = 0

    def __init__(self, _session):
        pass

    async def active_camera_alert(self, _camera_id):
        return self.__class__.alert

    def add(self, entity):
        self.__class__.added.append(entity)
        if getattr(entity, "alert_type", None) == SecurityAlertType.CAMERA_OFFLINE:
            self.__class__.alert = entity

    async def commit(self):
        self.__class__.commits += 1


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


def test_camera_outage_is_deduplicated_and_auto_resolved(monkeypatch):
    OperationalRepository.alert = None
    OperationalRepository.added = []
    OperationalRepository.commits = 0
    monkeypatch.setattr(
        "app.services.policy_service.PolicyRepository",
        OperationalRepository,
    )
    service = OperationalSecurityAlertService(lambda: SessionContext())
    camera_id = uuid4()
    now = datetime.now(UTC)

    async def exercise():
        await service.camera_health_changed(
            camera_id,
            status="OFFLINE",
            occurred_at=now,
            reason="No fresh frame",
        )
        await service.camera_health_changed(
            camera_id,
            status="OFFLINE",
            occurred_at=now,
            reason="No fresh frame",
        )
        await service.camera_health_changed(
            camera_id,
            status="ONLINE",
            occurred_at=now,
            reason=None,
        )

    asyncio.run(exercise())

    alerts = [
        item
        for item in OperationalRepository.added
        if getattr(item, "alert_type", None)
        == SecurityAlertType.CAMERA_OFFLINE
    ]
    assert len(alerts) == 1
    assert alerts[0].status == SecurityAlertStatus.RESOLVED
    assert alerts[0].resolution_note == (
        "Camera stream recovered automatically."
    )
