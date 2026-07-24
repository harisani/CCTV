"""Persistence boundary for event-time global journey correlation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BodyCandidate,
    BodyEmbedding,
    CaptureEvent,
    GlobalJourney,
    IdentityMatch,
    IdentityReviewStatus,
    JourneyCorrelation,
    JourneyCorrelationDecision,
    JourneyEvent,
    JourneyStatus,
    PPEAnalysis,
    ZoneAdjacency,
)


@dataclass(frozen=True, slots=True)
class JourneyAnchor:
    journey: GlobalJourney
    event: JourneyEvent
    temporal_relation: str
    body_similarity: float | None = None


class JourneyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_correlation(self) -> None:
        """Serialize short crossing decisions to avoid duplicate journeys."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(74823901)")
        )

    async def get_capture(
        self, capture_id: UUID
    ) -> CaptureEvent | None:
        return await self.session.scalar(
            select(CaptureEvent)
            .where(CaptureEvent.id == capture_id)
            .options(selectinload(CaptureEvent.tracking))
        )

    async def identity_matches(
        self, capture_id: UUID
    ) -> list[IdentityMatch]:
        return list(
            (
                await self.session.scalars(
                    select(IdentityMatch)
                    .where(IdentityMatch.capture_event_id == capture_id)
                    .order_by(IdentityMatch.confidence_score.desc())
                )
            ).all()
        )

    async def ppe_analysis(
        self, capture_id: UUID
    ) -> PPEAnalysis | None:
        return await self.session.scalar(
            select(PPEAnalysis).where(
                PPEAnalysis.capture_event_id == capture_id
            )
        )

    async def body_embedding(
        self, capture_id: UUID
    ) -> BodyEmbedding | None:
        return await self.session.scalar(
            select(BodyEmbedding)
            .join(
                BodyCandidate,
                BodyCandidate.id == BodyEmbedding.body_candidate_id,
            )
            .where(
                BodyCandidate.capture_event_id == capture_id,
                BodyCandidate.selected.is_(True),
                BodyEmbedding.active.is_(True),
            )
            .order_by(BodyEmbedding.quality_score.desc())
            .limit(1)
        )

    async def existing_correlation(
        self, capture_id: UUID
    ) -> JourneyCorrelation | None:
        return await self.session.scalar(
            select(JourneyCorrelation).where(
                JourneyCorrelation.capture_event_id == capture_id
            )
        )

    async def journey(self, journey_id: UUID) -> GlobalJourney | None:
        return await self.session.get(GlobalJourney, journey_id)

    async def event(self, event_id: UUID) -> JourneyEvent | None:
        return await self.session.get(JourneyEvent, event_id)

    async def candidate_anchors(
        self,
        *,
        occurred_at: datetime,
        max_gap_seconds: float,
        limit: int,
    ) -> list[JourneyAnchor]:
        lower = occurred_at - timedelta(seconds=max_gap_seconds)
        upper = occurred_at + timedelta(seconds=max_gap_seconds)
        journeys = list(
            (
                await self.session.scalars(
                    select(GlobalJourney)
                    .where(
                        GlobalJourney.status.in_(
                            (
                                JourneyStatus.ACTIVE,
                                JourneyStatus.NEED_REVIEW,
                            )
                        ),
                        GlobalJourney.first_seen_at <= upper,
                        GlobalJourney.last_seen_at >= lower,
                    )
                    .order_by(GlobalJourney.last_seen_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        if not journeys:
            return []
        distance = func.abs(
            func.extract(
                "epoch", JourneyEvent.occurred_at - occurred_at
            )
        )
        nearest_events = list(
            (
                await self.session.scalars(
                    select(JourneyEvent)
                    .where(
                        JourneyEvent.journey_id.in_(
                            [item.id for item in journeys]
                        )
                    )
                    .distinct(JourneyEvent.journey_id)
                    .order_by(JourneyEvent.journey_id, distance)
                )
            ).all()
        )
        event_by_journey = {
            item.journey_id: item for item in nearest_events
        }
        return [
            JourneyAnchor(
                journey,
                event_by_journey[journey.id],
                (
                    "PREVIOUS"
                    if event_by_journey[journey.id].occurred_at
                    <= occurred_at
                    else "NEXT"
                ),
            )
            for journey in journeys
            if journey.id in event_by_journey
        ]

    async def body_similarities(
        self,
        embedding: Sequence[float],
        *,
        model_version_id: UUID,
        capture_ids: list[UUID],
    ) -> dict[UUID, float]:
        if not capture_ids:
            return {}
        distance = BodyEmbedding.embedding.cosine_distance(
            list(embedding)
        ).label("distance")
        rows = (
            await self.session.execute(
                select(
                    BodyCandidate.capture_event_id,
                    func.min(distance),
                )
                .join(
                    BodyEmbedding,
                    BodyEmbedding.body_candidate_id == BodyCandidate.id,
                )
                .where(
                    BodyCandidate.capture_event_id.in_(capture_ids),
                    BodyCandidate.selected.is_(True),
                    BodyEmbedding.model_version_id == model_version_id,
                    BodyEmbedding.active.is_(True),
                )
                .group_by(BodyCandidate.capture_event_id)
            )
        ).all()
        return {
            capture_id: max(
                -1.0, min(1.0, 1.0 - float(distance_value))
            )
            for capture_id, distance_value in rows
        }

    async def adjacencies(self) -> list[ZoneAdjacency]:
        return list(
            (
                await self.session.scalars(
                    select(ZoneAdjacency).where(
                        ZoneAdjacency.enabled.is_(True)
                    )
                )
            ).all()
        )

    def add(self, entity: Any) -> None:
        self.session.add(entity)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def list_journeys(
        self,
        *,
        person_id: UUID | None,
        zone_id: UUID | None,
        camera_id: UUID | None,
        status: JourneyStatus | None,
        needs_review: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[GlobalJourney], int]:
        statement = select(GlobalJourney)
        if person_id is not None:
            statement = statement.where(
                GlobalJourney.identity_person_id == person_id
            )
        if zone_id is not None:
            statement = statement.where(
                GlobalJourney.current_zone_id == zone_id
            )
        if camera_id is not None:
            statement = statement.where(
                GlobalJourney.last_camera_id == camera_id
            )
        if status is not None:
            statement = statement.where(GlobalJourney.status == status)
        if needs_review is not None:
            statement = statement.where(
                GlobalJourney.review_status
                == (
                    IdentityReviewStatus.PENDING
                    if needs_review
                    else IdentityReviewStatus.NOT_REQUIRED
                )
            )
        if start_at is not None:
            statement = statement.where(
                GlobalJourney.last_seen_at >= start_at
            )
        if end_at is not None:
            statement = statement.where(
                GlobalJourney.first_seen_at <= end_at
            )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(GlobalJourney.last_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_events(
        self,
        *,
        journey_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[JourneyEvent], int]:
        statement = select(JourneyEvent).where(
            JourneyEvent.journey_id == journey_id
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(
                JourneyEvent.occurred_at, JourneyEvent.created_at
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_correlations(
        self,
        *,
        journey_id: UUID | None,
        capture_id: UUID | None,
        decision: JourneyCorrelationDecision | None,
        impossible_travel: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[JourneyCorrelation], int]:
        statement = select(JourneyCorrelation)
        if journey_id is not None:
            statement = statement.where(
                JourneyCorrelation.journey_id == journey_id
            )
        if capture_id is not None:
            statement = statement.where(
                JourneyCorrelation.capture_event_id == capture_id
            )
        if decision is not None:
            statement = statement.where(
                JourneyCorrelation.decision == decision
            )
        if impossible_travel is not None:
            statement = statement.where(
                JourneyCorrelation.impossible_travel
                == impossible_travel
            )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(JourneyCorrelation.correlated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)
