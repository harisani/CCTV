"""Conservative event-time correlation of local tracks into global journeys."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Sequence
from uuid import UUID, uuid4

from app.models import (
    GlobalJourney,
    IdentityDecision,
    IdentityMatch,
    IdentityReviewStatus,
    JourneyCorrelation,
    JourneyCorrelationDecision,
    JourneyEvent,
    JourneyEventType,
    JourneyStatus,
    ZoneAdjacency,
)
from app.repository.journey_repository import (
    JourneyAnchor,
    JourneyRepository,
)


@dataclass(frozen=True, slots=True)
class IdentitySignal:
    person_id: UUID | None
    external_subject_key: str | None
    decision: IdentityDecision
    confidence: float
    sources: tuple[str, ...]

    @property
    def known(self) -> bool:
        return self.person_id is not None or bool(
            self.external_subject_key
        )


@dataclass(frozen=True, slots=True)
class JourneyObservation:
    capture_id: UUID
    tracking_id: UUID | None
    camera_id: UUID
    origin_zone_id: UUID | None
    destination_zone_id: UUID | None
    current_zone_id: UUID | None
    occurred_at: datetime
    identity: IdentitySignal
    body_embedding: Sequence[float] | None
    body_model_version_id: UUID | None
    dominant_color: str | None


@dataclass(frozen=True, slots=True)
class CandidateScore:
    anchor: JourneyAnchor
    score: float
    identity_score: float
    topology_score: float
    time_score: float
    appearance_score: float
    impossible_travel: bool
    compatible_identity: bool
    reason: str


@dataclass(frozen=True, slots=True)
class JourneyCorrelationResult:
    journey: GlobalJourney
    event: JourneyEvent
    correlation: JourneyCorrelation
    needs_review: bool


class JourneyCorrelationEngine:
    """Pure multi-signal scorer; hard topology/identity conflicts never merge."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def score(
        self,
        observation: JourneyObservation,
        anchor: JourneyAnchor,
        adjacencies: list[ZoneAdjacency],
    ) -> CandidateScore:
        identity_score, compatible = self._identity_score(
            observation.identity, anchor.journey
        )
        topology, time_score, impossible, topology_reason = (
            self._topology_score(observation, anchor, adjacencies)
        )
        appearance = self._appearance_score(observation, anchor)
        same_track = (
            observation.tracking_id is not None
            and observation.tracking_id == anchor.event.tracking_id
        )
        if not compatible:
            score = 0.0
            reason = "IDENTITY_CONFLICT"
        elif impossible:
            score = 0.0
            reason = topology_reason
        elif same_track:
            score = 1.0
            reason = "SAME_LOCAL_TRACK"
        elif observation.identity.known:
            score = (
                0.45 * identity_score
                + 0.25 * topology
                + 0.15 * time_score
                + 0.15 * appearance
            )
            reason = "KNOWN_IDENTITY_MULTI_SIGNAL"
        else:
            score = (
                0.35 * topology
                + 0.20 * time_score
                + 0.45 * appearance
            )
            reason = "UNKNOWN_APPEARANCE_TOPOLOGY"
        return CandidateScore(
            anchor=anchor,
            score=round(max(0.0, min(1.0, score)), 6),
            identity_score=round(identity_score, 6),
            topology_score=round(topology, 6),
            time_score=round(time_score, 6),
            appearance_score=round(appearance, 6),
            impossible_travel=impossible,
            compatible_identity=compatible,
            reason=reason,
        )

    def threshold(self, observation: JourneyObservation) -> float:
        return (
            self._settings.journey_match_threshold
            if observation.identity.known
            else self._settings.journey_unknown_match_threshold
        )

    def _identity_score(
        self, signal: IdentitySignal, journey: GlobalJourney
    ) -> tuple[float, bool]:
        if signal.person_id is not None:
            if (
                journey.identity_person_id is not None
                and journey.identity_person_id != signal.person_id
            ):
                return 0.0, False
            return (
                1.0
                if journey.identity_person_id == signal.person_id
                else 0.65,
                True,
            )
        if signal.external_subject_key:
            if (
                journey.identity_external_subject_key
                and journey.identity_external_subject_key
                != signal.external_subject_key
            ):
                return 0.0, False
            return (
                1.0
                if journey.identity_external_subject_key
                == signal.external_subject_key
                else 0.65,
                True,
            )
        return (
            0.2
            if journey.identity_person_id
            or journey.identity_external_subject_key
            else 0.0,
            True,
        )

    def _appearance_score(
        self, observation: JourneyObservation, anchor: JourneyAnchor
    ) -> float:
        body_score: float | None = None
        if anchor.body_similarity is not None:
            minimum = self._settings.journey_min_body_similarity
            body_score = max(
                0.0,
                min(
                    1.0,
                    (anchor.body_similarity - minimum)
                    / max(0.000001, 1.0 - minimum),
                ),
            )
        anchor_color = (
            anchor.event.evidence_metadata.get("dominant_color")
            if anchor.event.evidence_metadata
            else None
        )
        color_score = (
            1.0
            if observation.dominant_color
            and anchor_color == observation.dominant_color
            else 0.0
        )
        if body_score is not None:
            return 0.9 * body_score + 0.1 * color_score
        return 0.2 * color_score

    def _topology_score(
        self,
        observation: JourneyObservation,
        anchor: JourneyAnchor,
        adjacencies: list[ZoneAdjacency],
    ) -> tuple[float, float, bool, str]:
        delta = abs(
            (observation.occurred_at - anchor.event.occurred_at)
            .total_seconds()
        )
        if delta > self._settings.journey_max_gap_seconds:
            return 0.0, 0.0, True, "JOURNEY_GAP_EXCEEDED"
        if anchor.temporal_relation == "PREVIOUS":
            source = anchor.event.current_zone_id
            target = (
                observation.origin_zone_id
                or observation.current_zone_id
            )
        else:
            source = observation.current_zone_id
            target = (
                anchor.event.origin_zone_id
                or anchor.event.current_zone_id
            )
        time_score = max(
            0.0,
            1.0 - delta / self._settings.journey_max_gap_seconds,
        )
        if source is None or target is None:
            return (
                self._settings.journey_missing_topology_score,
                time_score,
                False,
                "TOPOLOGY_INCOMPLETE",
            )
        if source == target:
            return 1.0, time_score, False, "SAME_ZONE"
        route = next(
            (
                item
                for item in adjacencies
                if (
                    item.source_zone_id == source
                    and item.target_zone_id == target
                )
                or (
                    item.bidirectional
                    and item.source_zone_id == target
                    and item.target_zone_id == source
                )
            ),
            None,
        )
        if route is None:
            return 0.0, 0.0, True, "NON_ADJACENT_ZONES"
        skew = self._settings.journey_clock_skew_seconds
        if (
            delta + skew < route.minimum_travel_seconds
            or delta - skew > route.maximum_travel_seconds
        ):
            return 0.0, 0.0, True, "TRAVEL_TIME_OUTSIDE_ROUTE"
        route_time = max(route.maximum_travel_seconds, 1.0)
        return (
            1.0,
            max(0.0, 1.0 - delta / route_time),
            False,
            "ADJACENT_ROUTE",
        )


class JourneyCorrelationService:
    def __init__(
        self,
        repository: JourneyRepository,
        settings: Any,
        *,
        engine: JourneyCorrelationEngine | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._engine = engine or JourneyCorrelationEngine(settings)

    async def correlate(
        self, capture_id: UUID
    ) -> JourneyCorrelationResult:
        await self._repository.lock_correlation()
        existing = await self._repository.existing_correlation(capture_id)
        if existing is not None:
            journey = await self._repository.journey(existing.journey_id)
            event = await self._repository.event(existing.journey_event_id)
            if journey is None or event is None:
                raise LookupError("Journey correlation references are missing")
            return JourneyCorrelationResult(
                journey,
                event,
                existing,
                journey.review_status == IdentityReviewStatus.PENDING,
            )
        observation = await self._observation(capture_id)
        anchors = await self._repository.candidate_anchors(
            occurred_at=observation.occurred_at,
            max_gap_seconds=self._settings.journey_max_gap_seconds,
            limit=self._settings.journey_candidate_limit,
        )
        if observation.body_embedding is not None:
            similarities = await self._repository.body_similarities(
                observation.body_embedding,
                model_version_id=observation.body_model_version_id,
                capture_ids=[
                    item.event.capture_event_id for item in anchors
                ],
            )
            anchors = [
                replace(
                    item,
                    body_similarity=similarities.get(
                        item.event.capture_event_id
                    ),
                )
                for item in anchors
            ]
        adjacencies = await self._repository.adjacencies()
        scores = sorted(
            (
                self._engine.score(
                    observation, anchor, adjacencies
                )
                for anchor in anchors
            ),
            key=lambda item: item.score,
            reverse=True,
        )
        eligible = [
            item
            for item in scores
            if item.compatible_identity and not item.impossible_travel
        ]
        threshold = self._engine.threshold(observation)
        best = eligible[0] if eligible else None
        second = eligible[1] if len(eligible) > 1 else None
        ambiguous = bool(
            best
            and second
            and best.score >= threshold
            and best.score - second.score
            < self._settings.journey_ambiguity_margin
        )
        impossible = any(
            item.impossible_travel
            and item.compatible_identity
            and (
                item.identity_score >= 0.65
                or (
                    item.anchor.body_similarity is not None
                    and item.anchor.body_similarity
                    >= self._settings.journey_min_body_similarity
                )
            )
            for item in scores
        )
        if best is not None and best.score >= threshold and not ambiguous:
            journey = best.anchor.journey
            decision = JourneyCorrelationDecision.MATCHED
            chosen = best
            needs_review = (
                self._identity_needs_review(observation.identity)
                or journey.review_status
                == IdentityReviewStatus.PENDING
            )
        else:
            journey = self._new_journey(observation)
            self._repository.add(journey)
            await self._repository.flush()
            chosen = best
            if ambiguous:
                decision = JourneyCorrelationDecision.AMBIGUOUS
            elif impossible:
                decision = JourneyCorrelationDecision.IMPOSSIBLE_TRAVEL
            else:
                decision = JourneyCorrelationDecision.CREATED
            needs_review = (
                decision
                in (
                    JourneyCorrelationDecision.AMBIGUOUS,
                    JourneyCorrelationDecision.IMPOSSIBLE_TRAVEL,
                )
                or self._identity_needs_review(observation.identity)
            )

        event = self._new_event(journey.id, observation)
        self._repository.add(event)
        await self._repository.flush()
        self._apply_event(journey, event, observation, needs_review)
        correlation = self._new_correlation(
            observation=observation,
            journey=journey,
            event=event,
            decision=decision,
            chosen=chosen,
            second=second,
            candidate_count=len(scores),
            impossible=impossible,
            threshold=threshold,
            ambiguity_margin=self._settings.journey_ambiguity_margin,
        )
        self._repository.add(correlation)
        await self._repository.commit()
        return JourneyCorrelationResult(
            journey, event, correlation, needs_review
        )

    async def list_journeys(self, **filters: Any) -> Any:
        return await self._repository.list_journeys(**filters)

    async def get_journey(
        self, journey_id: UUID
    ) -> GlobalJourney | None:
        return await self._repository.journey(journey_id)

    async def list_events(self, **filters: Any) -> Any:
        return await self._repository.list_events(**filters)

    async def list_correlations(self, **filters: Any) -> Any:
        return await self._repository.list_correlations(**filters)

    async def _observation(
        self, capture_id: UUID
    ) -> JourneyObservation:
        capture = await self._repository.get_capture(capture_id)
        if capture is None:
            raise LookupError("Capture event not found")
        matches = await self._repository.identity_matches(capture_id)
        identity = self._identity_signal(matches)
        body = await self._repository.body_embedding(capture_id)
        ppe = await self._repository.ppe_analysis(capture_id)
        metadata = capture.capture_metadata or {}
        origin = self._uuid(metadata.get("origin_zone_id"))
        destination = self._uuid(
            metadata.get("destination_zone_id")
        )
        current_zone = destination or capture.zone_id
        color = None
        if ppe and ppe.color_observation:
            raw_color = ppe.color_observation.get("dominant_color")
            color = str(raw_color) if raw_color else None
        return JourneyObservation(
            capture_id=capture.id,
            tracking_id=capture.tracking_id,
            camera_id=capture.camera_id,
            origin_zone_id=origin,
            destination_zone_id=destination,
            current_zone_id=current_zone,
            occurred_at=capture.captured_at,
            identity=identity,
            body_embedding=body.embedding if body else None,
            body_model_version_id=(
                body.model_version_id if body else None
            ),
            dominant_color=color,
        )

    @staticmethod
    def _identity_signal(
        matches: list[IdentityMatch],
    ) -> IdentitySignal:
        confirmed = [
            item
            for item in matches
            if item.decision == IdentityDecision.CONFIRMED
            and (
                item.candidate_person_id is not None
                or item.candidate_external_subject_key
            )
        ]
        probable = [
            item
            for item in matches
            if item.decision == IdentityDecision.PROBABLE
            and (
                item.candidate_person_id is not None
                or item.candidate_external_subject_key
            )
        ]
        pool = confirmed or probable
        subjects = {
            (
                item.candidate_person_id,
                item.candidate_external_subject_key,
            )
            for item in pool
        }
        if len(subjects) > 1 or any(
            item.decision == IdentityDecision.CONFLICT
            for item in matches
        ):
            return IdentitySignal(
                None,
                None,
                IdentityDecision.CONFLICT,
                max(
                    (item.confidence_score for item in matches),
                    default=0.0,
                ),
                tuple(item.modality.value for item in matches),
            )
        if pool:
            best = max(pool, key=lambda item: item.confidence_score)
            return IdentitySignal(
                best.candidate_person_id,
                best.candidate_external_subject_key,
                best.decision,
                best.confidence_score,
                tuple(item.modality.value for item in pool),
            )
        decision = (
            IdentityDecision.UNRESOLVED
            if any(
                item.decision == IdentityDecision.UNRESOLVED
                for item in matches
            )
            else IdentityDecision.UNKNOWN
        )
        return IdentitySignal(
            None,
            None,
            decision,
            0.0,
            tuple(item.modality.value for item in matches),
        )

    @staticmethod
    def _identity_needs_review(signal: IdentitySignal) -> bool:
        return signal.decision in (
            IdentityDecision.PROBABLE,
            IdentityDecision.UNRESOLVED,
            IdentityDecision.UNKNOWN,
            IdentityDecision.CONFLICT,
        )

    @staticmethod
    def _new_journey(
        observation: JourneyObservation,
    ) -> GlobalJourney:
        journey_id = uuid4()
        needs_review = JourneyCorrelationService._identity_needs_review(
            observation.identity
        )
        return GlobalJourney(
            id=journey_id,
            journey_key=f"J-{journey_id.hex[:12].upper()}",
            identity_person_id=observation.identity.person_id,
            identity_external_subject_key=(
                observation.identity.external_subject_key
            ),
            identity_decision=observation.identity.decision,
            identity_confidence=observation.identity.confidence,
            first_seen_at=observation.occurred_at,
            last_seen_at=observation.occurred_at,
            current_zone_id=observation.current_zone_id,
            last_camera_id=observation.camera_id,
            status=(
                JourneyStatus.NEED_REVIEW
                if needs_review
                else JourneyStatus.ACTIVE
            ),
            review_status=(
                IdentityReviewStatus.PENDING
                if needs_review
                else IdentityReviewStatus.NOT_REQUIRED
            ),
            event_count=0,
            version=1,
        )

    @staticmethod
    def _new_event(
        journey_id: UUID, observation: JourneyObservation
    ) -> JourneyEvent:
        return JourneyEvent(
            id=uuid4(),
            idempotency_key=f"journey-event:{observation.capture_id}",
            journey_id=journey_id,
            capture_event_id=observation.capture_id,
            tracking_id=observation.tracking_id,
            camera_id=observation.camera_id,
            origin_zone_id=observation.origin_zone_id,
            destination_zone_id=observation.destination_zone_id,
            current_zone_id=observation.current_zone_id,
            event_type=(
                JourneyEventType.ZONE_TRANSITION
                if observation.origin_zone_id
                or observation.destination_zone_id
                else JourneyEventType.OBSERVATION
            ),
            identity_person_id=observation.identity.person_id,
            identity_external_subject_key=(
                observation.identity.external_subject_key
            ),
            identity_decision=observation.identity.decision,
            identity_confidence=observation.identity.confidence,
            occurred_at=observation.occurred_at,
            evidence_metadata={
                "identity_sources": list(observation.identity.sources),
                "dominant_color": observation.dominant_color,
                "body_embedding_available": (
                    observation.body_embedding is not None
                ),
            },
        )

    @staticmethod
    def _apply_event(
        journey: GlobalJourney,
        event: JourneyEvent,
        observation: JourneyObservation,
        needs_review: bool,
    ) -> None:
        is_latest = observation.occurred_at >= journey.last_seen_at
        journey.first_seen_at = min(
            journey.first_seen_at, observation.occurred_at
        )
        journey.last_seen_at = max(
            journey.last_seen_at, observation.occurred_at
        )
        if is_latest:
            journey.current_zone_id = observation.current_zone_id
            journey.last_camera_id = observation.camera_id
            journey.last_event_id = event.id
        if (
            journey.identity_person_id is None
            and observation.identity.person_id is not None
        ):
            journey.identity_person_id = observation.identity.person_id
            journey.identity_decision = observation.identity.decision
            journey.identity_confidence = observation.identity.confidence
        elif (
            journey.identity_external_subject_key is None
            and observation.identity.external_subject_key
        ):
            journey.identity_external_subject_key = (
                observation.identity.external_subject_key
            )
            journey.identity_decision = observation.identity.decision
            journey.identity_confidence = observation.identity.confidence
        elif (
            observation.identity.person_id
            == journey.identity_person_id
            or (
                observation.identity.external_subject_key
                and observation.identity.external_subject_key
                == journey.identity_external_subject_key
            )
        ):
            journey.identity_confidence = max(
                journey.identity_confidence,
                observation.identity.confidence,
            )
            if observation.identity.decision == IdentityDecision.CONFIRMED:
                journey.identity_decision = IdentityDecision.CONFIRMED
        journey.event_count += 1
        journey.version += 1
        if needs_review:
            journey.status = JourneyStatus.NEED_REVIEW
            journey.review_status = IdentityReviewStatus.PENDING

    @staticmethod
    def _new_correlation(
        *,
        observation: JourneyObservation,
        journey: GlobalJourney,
        event: JourneyEvent,
        decision: JourneyCorrelationDecision,
        chosen: CandidateScore | None,
        second: CandidateScore | None,
        candidate_count: int,
        impossible: bool,
        threshold: float,
        ambiguity_margin: float,
    ) -> JourneyCorrelation:
        return JourneyCorrelation(
            id=uuid4(),
            idempotency_key=f"journey-correlation:{observation.capture_id}",
            capture_event_id=observation.capture_id,
            journey_id=journey.id,
            journey_event_id=event.id,
            anchor_journey_event_id=(
                chosen.anchor.event.id if chosen else None
            ),
            decision=decision,
            correlation_score=chosen.score if chosen else 0.0,
            second_best_score=second.score if second else None,
            identity_score=chosen.identity_score if chosen else 0.0,
            topology_score=chosen.topology_score if chosen else 0.0,
            time_score=chosen.time_score if chosen else 0.0,
            appearance_score=chosen.appearance_score if chosen else 0.0,
            candidate_count=candidate_count,
            impossible_travel=(
                decision
                == JourneyCorrelationDecision.IMPOSSIBLE_TRAVEL
            ),
            reasoning_metadata={
                "reason": chosen.reason if chosen else "NO_CANDIDATE",
                "threshold": threshold,
                "ambiguity_margin": ambiguity_margin,
                "event_time_correlation": True,
                "impossible_candidate_seen": impossible,
                "identity_decision": observation.identity.decision.value,
            },
            correlated_at=datetime.now(UTC),
        )

    @staticmethod
    def _uuid(value: object) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None
