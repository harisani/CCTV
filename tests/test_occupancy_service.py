from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import (
    IdentityDecision,
    JourneyCorrelationDecision,
    OccupancyFact,
    OccupancyFactType,
    OccupancySessionState,
    OccupancySubjectType,
)
from app.services.occupancy_service import OccupancyProjectionEngine


def _fact(
    *,
    occurred_at,
    current_zone,
    origin=None,
    destination=None,
    decision=IdentityDecision.CONFIRMED,
    person_id=None,
):
    event_id = uuid4()
    return OccupancyFact(
        id=uuid4(),
        idempotency_key=f"fact:{event_id}",
        journey_id=JOURNEY_ID,
        journey_event_id=event_id,
        camera_id=uuid4(),
        origin_zone_id=origin,
        destination_zone_id=destination,
        current_zone_id=current_zone,
        fact_type=(
            OccupancyFactType.TRANSITION
            if origin and destination
            else (
                OccupancyFactType.EXIT
                if current_zone is None
                else OccupancyFactType.ENTER
            )
        ),
        subject_type=(
            OccupancySubjectType.EMPLOYEE
            if person_id
            else OccupancySubjectType.UNKNOWN
        ),
        person_id=person_id,
        external_subject_key=None,
        identity_decision=decision,
        identity_confidence=0.95 if person_id else 0.0,
        correlation_decision=JourneyCorrelationDecision.MATCHED,
        correlation_score=0.9,
        occurred_at=occurred_at,
        fact_metadata={},
        created_at=occurred_at,
    )


JOURNEY_ID = uuid4()


def test_reconstructs_enter_transition_and_exit_sessions():
    now = datetime.now(UTC)
    person_id = uuid4()
    zone_a, zone_b = uuid4(), uuid4()
    enter = _fact(
        occurred_at=now,
        current_zone=zone_a,
        destination=zone_a,
        person_id=person_id,
    )
    observation = _fact(
        occurred_at=now + timedelta(seconds=10),
        current_zone=zone_a,
        person_id=person_id,
    )
    transition = _fact(
        occurred_at=now + timedelta(seconds=20),
        current_zone=zone_b,
        origin=zone_a,
        destination=zone_b,
        person_id=person_id,
    )
    exit_fact = _fact(
        occurred_at=now + timedelta(seconds=30),
        current_zone=None,
        origin=zone_b,
        person_id=person_id,
    )

    sessions = OccupancyProjectionEngine().reconstruct(
        [enter, observation, transition, exit_fact]
    )

    assert len(sessions) == 2
    assert sessions[0].zone_id == zone_a
    assert sessions[0].state == OccupancySessionState.EXITED
    assert sessions[0].last_seen_at == transition.occurred_at
    assert sessions[1].zone_id == zone_b
    assert sessions[1].state == OccupancySessionState.EXITED
    assert sessions[1].exited_at == exit_fact.occurred_at


def test_out_of_order_processing_reconstructs_by_event_time():
    now = datetime.now(UTC)
    zone_a, zone_b = uuid4(), uuid4()
    later = _fact(
        occurred_at=now + timedelta(seconds=30),
        current_zone=zone_b,
        origin=zone_a,
        destination=zone_b,
    )
    earlier = _fact(
        occurred_at=now,
        current_zone=zone_a,
        destination=zone_a,
    )

    sessions = OccupancyProjectionEngine().reconstruct([later, earlier])

    assert [item.zone_id for item in sessions] == [zone_a, zone_b]
    assert sessions[0].state == OccupancySessionState.EXITED
    assert sessions[1].state == OccupancySessionState.ACTIVE


def test_unknown_subject_remains_active_but_requires_review():
    fact = _fact(
        occurred_at=datetime.now(UTC),
        current_zone=uuid4(),
        decision=IdentityDecision.UNKNOWN,
    )

    session = OccupancyProjectionEngine().reconstruct([fact])[0]

    assert session.state == OccupancySessionState.ACTIVE
    assert session.subject_type == OccupancySubjectType.UNKNOWN
    assert session.review_status.value == "PENDING"


def test_exit_without_open_session_does_not_create_negative_occupancy():
    exit_fact = _fact(
        occurred_at=datetime.now(UTC),
        current_zone=None,
        origin=uuid4(),
    )

    sessions = OccupancyProjectionEngine().reconstruct([exit_fact])

    assert sessions == []
