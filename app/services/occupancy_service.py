"""Event-sourced occupancy reconstruction based on global journeys."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.models import (
    IdentityDecision,
    IdentityReviewStatus,
    JourneyCorrelation,
    JourneyCorrelationDecision,
    JourneyEvent,
    OccupancyFact,
    OccupancyFactType,
    OccupancySession,
    OccupancySessionState,
    OccupancySubjectType,
)
from app.repository import OccupancyRepository


@dataclass(frozen=True, slots=True)
class SessionProjection:
    id: UUID
    journey_id: UUID
    zone_id: UUID
    subject_type: OccupancySubjectType
    person_id: UUID | None
    external_subject_key: str | None
    entry_journey_event_id: UUID
    exit_journey_event_id: UUID | None
    last_journey_event_id: UUID
    last_camera_id: UUID
    state: OccupancySessionState
    identity_decision: IdentityDecision
    identification_confidence: float
    review_status: IdentityReviewStatus
    entered_at: datetime
    exited_at: datetime | None
    last_seen_at: datetime
    state_reason: str


@dataclass(frozen=True, slots=True)
class OccupancyProcessingResult:
    fact: OccupancyFact
    current_session: OccupancySession | None
    session_count: int
    active_count: int
    needs_review: bool


class OccupancyProjectionEngine:
    """Rebuild deterministic zone sessions from event-time ordered facts."""

    def reconstruct(
        self, facts: list[OccupancyFact]
    ) -> list[SessionProjection]:
        completed: list[SessionProjection] = []
        current: SessionProjection | None = None
        for fact in sorted(
            facts, key=lambda item: (item.occurred_at, item.created_at)
        ):
            target_zone = fact.current_zone_id
            if target_zone is None:
                if current is not None:
                    completed.append(
                        self._close(
                            current,
                            fact,
                            reason="VALID_ZONE_EXIT",
                        )
                    )
                    current = None
                continue
            if current is None:
                current = self._open(fact, target_zone)
                continue
            if current.zone_id == target_zone:
                current = self._observe(current, fact)
                continue
            completed.append(
                self._close(
                    current,
                    fact,
                    reason="ADJACENT_ZONE_ENTRY",
                )
            )
            current = self._open(fact, target_zone)
        if current is not None:
            completed.append(current)
        return completed

    def _open(
        self, fact: OccupancyFact, zone_id: UUID
    ) -> SessionProjection:
        review = self._review_status(fact)
        return SessionProjection(
            id=uuid5(
                NAMESPACE_URL,
                f"occupancy:{fact.journey_id}:"
                f"{fact.journey_event_id}",
            ),
            journey_id=fact.journey_id,
            zone_id=zone_id,
            subject_type=fact.subject_type,
            person_id=fact.person_id,
            external_subject_key=fact.external_subject_key,
            entry_journey_event_id=fact.journey_event_id,
            exit_journey_event_id=None,
            last_journey_event_id=fact.journey_event_id,
            last_camera_id=fact.camera_id,
            state=OccupancySessionState.ACTIVE,
            identity_decision=fact.identity_decision,
            identification_confidence=fact.identity_confidence,
            review_status=review,
            entered_at=fact.occurred_at,
            exited_at=None,
            last_seen_at=fact.occurred_at,
            state_reason="VALID_ZONE_ENTRY",
        )

    def _observe(
        self,
        current: SessionProjection,
        fact: OccupancyFact,
    ) -> SessionProjection:
        person_id = current.person_id or fact.person_id
        external = (
            current.external_subject_key or fact.external_subject_key
        )
        decision = current.identity_decision
        confidence = current.identification_confidence
        if fact.identity_confidence >= confidence:
            decision = fact.identity_decision
            confidence = fact.identity_confidence
        review = (
            IdentityReviewStatus.PENDING
            if current.review_status == IdentityReviewStatus.PENDING
            or self._review_status(fact)
            == IdentityReviewStatus.PENDING
            else IdentityReviewStatus.NOT_REQUIRED
        )
        return replace(
            current,
            subject_type=(
                OccupancySubjectType.EMPLOYEE
                if person_id or external
                else fact.subject_type
            ),
            person_id=person_id,
            external_subject_key=external,
            last_journey_event_id=fact.journey_event_id,
            last_camera_id=fact.camera_id,
            state=OccupancySessionState.ACTIVE,
            identity_decision=decision,
            identification_confidence=confidence,
            review_status=review,
            last_seen_at=fact.occurred_at,
            state_reason="CORRELATED_OBSERVATION",
        )

    @staticmethod
    def _close(
        current: SessionProjection,
        fact: OccupancyFact,
        *,
        reason: str,
    ) -> SessionProjection:
        return replace(
            current,
            exit_journey_event_id=fact.journey_event_id,
            last_journey_event_id=fact.journey_event_id,
            last_camera_id=fact.camera_id,
            state=OccupancySessionState.EXITED,
            exited_at=fact.occurred_at,
            last_seen_at=max(
                current.last_seen_at, fact.occurred_at
            ),
            state_reason=reason,
        )

    @staticmethod
    def _review_status(
        fact: OccupancyFact,
    ) -> IdentityReviewStatus:
        return (
            IdentityReviewStatus.NOT_REQUIRED
            if (
                fact.identity_decision == IdentityDecision.CONFIRMED
                and fact.correlation_decision
                in (
                    JourneyCorrelationDecision.CREATED,
                    JourneyCorrelationDecision.MATCHED,
                )
            )
            else IdentityReviewStatus.PENDING
        )


class OccupancyService:
    def __init__(
        self,
        repository: OccupancyRepository,
        settings: Any,
        *,
        engine: OccupancyProjectionEngine | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._engine = engine or OccupancyProjectionEngine()

    async def process_capture(
        self, capture_id: UUID
    ) -> OccupancyProcessingResult:
        correlation = await self._repository.correlation_for_capture(
            capture_id
        )
        if correlation is None:
            raise LookupError("Journey correlation not found")
        event = await self._repository.journey_event(
            correlation.journey_event_id
        )
        if event is None:
            raise LookupError("Journey event not found")
        await self._repository.lock_journey(event.journey_id)
        fact = await self._repository.fact_for_event(event.id)
        if fact is None:
            fact = self._fact(event, correlation)
            self._repository.add(fact)
            await self._repository.flush()
        facts = await self._repository.facts(event.journey_id)
        desired = self._engine.reconstruct(facts)
        sessions = await self._apply_projection(
            event.journey_id, desired
        )
        await self._repository.commit()
        current = next(
            (
                item
                for item in sessions
                if item.state == OccupancySessionState.ACTIVE
            ),
            None,
        )
        needs_review = any(
            item.review_status == IdentityReviewStatus.PENDING
            or item.state == OccupancySessionState.NEED_REVIEW
            for item in sessions
        )
        return OccupancyProcessingResult(
            fact=fact,
            current_session=current,
            session_count=len(sessions),
            active_count=sum(
                item.state == OccupancySessionState.ACTIVE
                for item in sessions
            ),
            needs_review=needs_review,
        )

    async def list_sessions(self, **filters: Any) -> Any:
        return await self._repository.list_sessions(**filters)

    async def list_facts(self, **filters: Any) -> Any:
        return await self._repository.list_facts(**filters)

    async def summary(self, zone_id: UUID | None) -> dict[str, int]:
        return await self._repository.summary(zone_id)

    async def _apply_projection(
        self,
        journey_id: UUID,
        desired: list[SessionProjection],
    ) -> list[OccupancySession]:
        existing = await self._repository.sessions(journey_id)
        by_entry = {
            item.entry_journey_event_id: item for item in existing
        }
        desired_entries = {
            item.entry_journey_event_id for item in desired
        }
        for stale in existing:
            if stale.entry_journey_event_id not in desired_entries:
                await self._repository.delete_session(stale)
        output: list[OccupancySession] = []
        for projection in desired:
            session = by_entry.get(projection.entry_journey_event_id)
            values = {
                field.name: getattr(projection, field.name)
                for field in fields(projection)
            }
            if session is None:
                session = OccupancySession(
                    **values,
                    reconstruction_version=1,
                )
                self._repository.add(session)
            else:
                previous_state = session.state
                preserve_lost = (
                    previous_state
                    in (
                        OccupancySessionState.TEMPORARILY_LOST,
                        OccupancySessionState.STALE,
                    )
                    and session.last_journey_event_id
                    == projection.last_journey_event_id
                    and projection.state
                    == OccupancySessionState.ACTIVE
                )
                for key, value in values.items():
                    setattr(session, key, value)
                if preserve_lost:
                    session.state = previous_state
                session.reconstruction_version += 1
            output.append(session)
        await self._repository.flush()
        return output

    @staticmethod
    def _fact(
        event: JourneyEvent,
        correlation: JourneyCorrelation,
    ) -> OccupancyFact:
        source_type = str(
            event.evidence_metadata.get("source_event_type") or ""
        ).upper()
        if (
            source_type == "EXIT"
            and event.current_zone_id is None
        ):
            fact_type = OccupancyFactType.EXIT
        elif event.origin_zone_id and event.destination_zone_id:
            fact_type = OccupancyFactType.TRANSITION
        elif source_type == "ENTER":
            fact_type = OccupancyFactType.ENTER
        else:
            fact_type = OccupancyFactType.OBSERVATION
        if event.identity_person_id or event.identity_external_subject_key:
            subject_type = OccupancySubjectType.EMPLOYEE
        elif event.identity_decision == IdentityDecision.UNKNOWN:
            subject_type = OccupancySubjectType.UNKNOWN
        else:
            subject_type = OccupancySubjectType.UNRESOLVED
        fact_id = uuid5(
            NAMESPACE_URL, f"occupancy-fact:{event.id}"
        )
        return OccupancyFact(
            id=fact_id,
            idempotency_key=f"occupancy-fact:{event.id}",
            journey_id=event.journey_id,
            journey_event_id=event.id,
            camera_id=event.camera_id,
            origin_zone_id=event.origin_zone_id,
            destination_zone_id=event.destination_zone_id,
            current_zone_id=event.current_zone_id,
            fact_type=fact_type,
            subject_type=subject_type,
            person_id=event.identity_person_id,
            external_subject_key=event.identity_external_subject_key,
            identity_decision=event.identity_decision,
            identity_confidence=event.identity_confidence,
            correlation_decision=correlation.decision,
            correlation_score=correlation.correlation_score,
            occurred_at=event.occurred_at,
            fact_metadata={
                "correlation_id": str(correlation.id),
                "projection_source": "GLOBAL_JOURNEY",
                "event_time_reconstruction": True,
            },
            created_at=datetime.now(UTC),
        )
