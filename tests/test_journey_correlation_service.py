from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import (
    BiometricModality,
    CaptureEvent,
    GlobalJourney,
    IdentityDecision,
    IdentityReviewStatus,
    JourneyEvent,
    JourneyEventType,
    JourneyStatus,
    ZoneAdjacency,
)
from app.repository.journey_repository import JourneyAnchor
from app.services.journey_correlation_service import (
    IdentitySignal,
    JourneyCorrelationEngine,
    JourneyCorrelationService,
    JourneyObservation,
)


class Settings:
    journey_match_threshold = 0.72
    journey_unknown_match_threshold = 0.82
    journey_ambiguity_margin = 0.08
    journey_max_gap_seconds = 900.0
    journey_candidate_limit = 100
    journey_min_body_similarity = 0.65
    journey_missing_topology_score = 0.35
    journey_clock_skew_seconds = 5.0


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _journey(person_id=None):
    now = datetime.now(UTC)
    return GlobalJourney(
        id=uuid4(),
        journey_key=f"J-{uuid4().hex[:12].upper()}",
        identity_person_id=person_id,
        identity_external_subject_key=None,
        identity_decision=(
            IdentityDecision.CONFIRMED
            if person_id
            else IdentityDecision.UNKNOWN
        ),
        identity_confidence=0.9 if person_id else 0.0,
        first_seen_at=now,
        last_seen_at=now,
        current_zone_id=uuid4(),
        last_camera_id=uuid4(),
        status=JourneyStatus.ACTIVE,
        review_status=IdentityReviewStatus.NOT_REQUIRED,
        event_count=1,
        version=1,
    )


def _anchor(journey, zone_id, occurred_at, *, relation="PREVIOUS"):
    event = JourneyEvent(
        id=uuid4(),
        idempotency_key=f"event:{uuid4()}",
        journey_id=journey.id,
        capture_event_id=uuid4(),
        tracking_id=uuid4(),
        camera_id=uuid4(),
        origin_zone_id=None,
        destination_zone_id=zone_id,
        current_zone_id=zone_id,
        event_type=JourneyEventType.OBSERVATION,
        identity_person_id=journey.identity_person_id,
        identity_external_subject_key=None,
        identity_decision=journey.identity_decision,
        identity_confidence=journey.identity_confidence,
        occurred_at=occurred_at,
        evidence_metadata={"dominant_color": "BLUE"},
    )
    return JourneyAnchor(journey, event, relation)


def _observation(
    *,
    person_id,
    origin_zone,
    current_zone,
    occurred_at,
    tracking_id=None,
):
    return JourneyObservation(
        capture_id=uuid4(),
        tracking_id=tracking_id or uuid4(),
        camera_id=uuid4(),
        origin_zone_id=origin_zone,
        destination_zone_id=current_zone,
        current_zone_id=current_zone,
        occurred_at=occurred_at,
        identity=IdentitySignal(
            person_id,
            None,
            (
                IdentityDecision.CONFIRMED
                if person_id
                else IdentityDecision.UNKNOWN
            ),
            0.95 if person_id else 0.0,
            ("FACE",) if person_id else ("BODY",),
        ),
        body_embedding=None,
        body_model_version_id=None,
        dominant_color="BLUE",
    )


def test_known_identity_merges_only_through_valid_timed_topology():
    now = datetime.now(UTC)
    person_id = uuid4()
    source, destination = uuid4(), uuid4()
    journey = _journey(person_id)
    anchor = _anchor(journey, source, now)
    adjacency = ZoneAdjacency(
        source_zone_id=source,
        target_zone_id=destination,
        minimum_travel_seconds=10,
        maximum_travel_seconds=300,
        bidirectional=True,
        enabled=True,
    )
    observation = _observation(
        person_id=person_id,
        origin_zone=destination,
        current_zone=destination,
        occurred_at=now + timedelta(seconds=60),
    )

    score = JourneyCorrelationEngine(Settings()).score(
        observation, anchor, [adjacency]
    )

    assert score.compatible_identity is True
    assert score.impossible_travel is False
    assert score.score >= Settings.journey_match_threshold
    assert score.reason == "KNOWN_IDENTITY_MULTI_SIGNAL"


def test_identity_conflict_is_never_merged_even_with_same_zone():
    now = datetime.now(UTC)
    journey = _journey(uuid4())
    zone_id = uuid4()
    anchor = _anchor(journey, zone_id, now)
    observation = _observation(
        person_id=uuid4(),
        origin_zone=zone_id,
        current_zone=zone_id,
        occurred_at=now + timedelta(seconds=5),
    )

    score = JourneyCorrelationEngine(Settings()).score(
        observation, anchor, []
    )

    assert score.compatible_identity is False
    assert score.score == 0.0
    assert score.reason == "IDENTITY_CONFLICT"


def test_non_adjacent_zone_is_impossible_travel_for_same_identity():
    now = datetime.now(UTC)
    person_id = uuid4()
    anchor = _anchor(_journey(person_id), uuid4(), now)
    observation = _observation(
        person_id=person_id,
        origin_zone=uuid4(),
        current_zone=uuid4(),
        occurred_at=now + timedelta(seconds=30),
    )

    score = JourneyCorrelationEngine(Settings()).score(
        observation, anchor, []
    )

    assert score.impossible_travel is True
    assert score.score == 0.0
    assert score.reason == "NON_ADJACENT_ZONES"


def test_unknown_person_can_match_with_strong_body_topology_and_time():
    now = datetime.now(UTC)
    zone_id = uuid4()
    anchor = _anchor(_journey(), zone_id, now)
    anchor = JourneyAnchor(
        anchor.journey,
        anchor.event,
        anchor.temporal_relation,
        body_similarity=0.95,
    )
    observation = _observation(
        person_id=None,
        origin_zone=zone_id,
        current_zone=zone_id,
        occurred_at=now + timedelta(seconds=10),
    )

    engine = JourneyCorrelationEngine(Settings())
    score = engine.score(observation, anchor, [])

    assert score.score >= engine.threshold(observation)
    assert score.appearance_score > 0.75
    assert score.reason == "UNKNOWN_APPEARANCE_TOPOLOGY"


def test_conflicting_confirmed_modalities_produce_conflict_signal():
    matches = [
        SimpleNamespace(
            decision=IdentityDecision.CONFIRMED,
            candidate_person_id=uuid4(),
            candidate_external_subject_key=None,
            confidence_score=0.9,
            modality=BiometricModality.FACE,
        ),
        SimpleNamespace(
            decision=IdentityDecision.CONFIRMED,
            candidate_person_id=uuid4(),
            candidate_external_subject_key=None,
            confidence_score=0.85,
            modality=BiometricModality.BODY,
        ),
    ]

    signal = JourneyCorrelationService._identity_signal(matches)

    assert signal.decision == IdentityDecision.CONFLICT
    assert signal.person_id is None


class FakeJourneyRepository:
    def __init__(self, captures, matches, adjacencies):
        self.captures = captures
        self.matches = matches
        self.routes = adjacencies
        self.journeys = {}
        self.events = {}
        self.correlations = {}

    async def lock_correlation(self):
        return None

    async def existing_correlation(self, capture_id):
        return self.correlations.get(capture_id)

    async def journey(self, journey_id):
        return self.journeys.get(journey_id)

    async def event(self, event_id):
        return self.events.get(event_id)

    async def get_capture(self, capture_id):
        return self.captures.get(capture_id)

    async def identity_matches(self, capture_id):
        return self.matches.get(capture_id, [])

    async def body_embedding(self, _capture_id):
        return None

    async def ppe_analysis(self, _capture_id):
        return None

    async def adjacencies(self):
        return self.routes

    async def candidate_anchors(self, **fields):
        occurred_at = fields["occurred_at"]
        anchors = []
        for journey in self.journeys.values():
            available = [
                event
                for event in self.events.values()
                if event.journey_id == journey.id
            ]
            if not available:
                continue
            event = min(
                available,
                key=lambda item: abs(
                    (occurred_at - item.occurred_at).total_seconds()
                ),
            )
            relation = (
                "PREVIOUS"
                if event.occurred_at <= occurred_at
                else "NEXT"
            )
            anchors.append(JourneyAnchor(journey, event, relation))
        return anchors

    async def body_similarities(self, *_args, **_fields):
        return {}

    def add(self, entity):
        from app.models import JourneyCorrelation

        if isinstance(entity, GlobalJourney):
            self.journeys[entity.id] = entity
        elif isinstance(entity, JourneyEvent):
            self.events[entity.id] = entity
        elif isinstance(entity, JourneyCorrelation):
            self.correlations[entity.capture_event_id] = entity

    async def flush(self):
        return None

    async def commit(self):
        return None


def _capture(capture_id, camera_id, zone_id, occurred_at):
    return CaptureEvent(
        id=capture_id,
        idempotency_key=f"capture:{capture_id}",
        camera_id=camera_id,
        zone_id=zone_id,
        tracking_id=uuid4(),
        status="PROCESSING",
        capture_metadata={
            "origin_zone_id": str(zone_id),
            "destination_zone_id": str(zone_id),
        },
        captured_at=occurred_at,
    )


def _confirmed_match(person_id):
    return SimpleNamespace(
        decision=IdentityDecision.CONFIRMED,
        candidate_person_id=person_id,
        candidate_external_subject_key=None,
        confidence_score=0.96,
        modality=BiometricModality.FACE,
    )


@pytest.mark.anyio
async def test_service_merges_two_camera_tracks_and_is_idempotent():
    now = datetime.now(UTC)
    person_id = uuid4()
    zone_id = uuid4()
    first_id, second_id = uuid4(), uuid4()
    repository = FakeJourneyRepository(
        {
            first_id: _capture(first_id, uuid4(), zone_id, now),
            second_id: _capture(
                second_id,
                uuid4(),
                zone_id,
                now + timedelta(seconds=20),
            ),
        },
        {
            first_id: [_confirmed_match(person_id)],
            second_id: [_confirmed_match(person_id)],
        },
        [],
    )
    service = JourneyCorrelationService(repository, Settings())

    first = await service.correlate(first_id)
    second = await service.correlate(second_id)
    repeated = await service.correlate(second_id)

    assert first.correlation.decision.value == "CREATED"
    assert second.correlation.decision.value == "MATCHED"
    assert second.journey.id == first.journey.id
    assert second.journey.event_count == 2
    assert repeated.correlation.id == second.correlation.id
    assert len(repository.events) == 2
