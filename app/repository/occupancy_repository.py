"""Persistence for immutable occupancy facts and reconstructed sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    JourneyCorrelation,
    JourneyEvent,
    OccupancyFact,
    OccupancySession,
    OccupancySessionState,
    OccupancySubjectType,
)


class OccupancyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_journey(self, journey_id: UUID) -> None:
        await self.session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:key, 0))"
            ),
            {"key": f"occupancy:{journey_id}"},
        )

    async def correlation_for_capture(
        self, capture_id: UUID
    ) -> JourneyCorrelation | None:
        return await self.session.scalar(
            select(JourneyCorrelation).where(
                JourneyCorrelation.capture_event_id == capture_id
            )
        )

    async def journey_event(
        self, event_id: UUID
    ) -> JourneyEvent | None:
        return await self.session.get(JourneyEvent, event_id)

    async def fact_for_event(
        self, event_id: UUID
    ) -> OccupancyFact | None:
        return await self.session.scalar(
            select(OccupancyFact).where(
                OccupancyFact.journey_event_id == event_id
            )
        )

    def add(self, entity: Any) -> None:
        self.session.add(entity)

    async def flush(self) -> None:
        await self.session.flush()

    async def facts(self, journey_id: UUID) -> list[OccupancyFact]:
        return list(
            (
                await self.session.scalars(
                    select(OccupancyFact)
                    .where(OccupancyFact.journey_id == journey_id)
                    .order_by(
                        OccupancyFact.occurred_at,
                        OccupancyFact.created_at,
                    )
                )
            ).all()
        )

    async def sessions(
        self, journey_id: UUID
    ) -> list[OccupancySession]:
        return list(
            (
                await self.session.scalars(
                    select(OccupancySession)
                    .where(OccupancySession.journey_id == journey_id)
                    .order_by(OccupancySession.entered_at)
                )
            ).all()
        )

    async def delete_session(self, session: OccupancySession) -> None:
        await self.session.delete(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def mark_camera_lost(
        self, camera_id: UUID, *, occurred_at: datetime
    ) -> int:
        result = await self.session.execute(
            update(OccupancySession)
            .where(
                OccupancySession.last_camera_id == camera_id,
                OccupancySession.state
                == OccupancySessionState.ACTIVE,
            )
            .values(
                state=OccupancySessionState.TEMPORARILY_LOST,
                state_reason="CAMERA_OFFLINE",
                updated_at=occurred_at,
            )
        )
        return int(result.rowcount or 0)

    async def list_sessions(
        self,
        *,
        zone_id: UUID | None,
        journey_id: UUID | None,
        person_id: UUID | None,
        state: OccupancySessionState | None,
        subject_type: OccupancySubjectType | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[OccupancySession], int]:
        statement = select(OccupancySession)
        if zone_id is not None:
            statement = statement.where(
                OccupancySession.zone_id == zone_id
            )
        if journey_id is not None:
            statement = statement.where(
                OccupancySession.journey_id == journey_id
            )
        if person_id is not None:
            statement = statement.where(
                OccupancySession.person_id == person_id
            )
        if state is not None:
            statement = statement.where(OccupancySession.state == state)
        if subject_type is not None:
            statement = statement.where(
                OccupancySession.subject_type == subject_type
            )
        if start_at is not None:
            statement = statement.where(
                OccupancySession.last_seen_at >= start_at
            )
        if end_at is not None:
            statement = statement.where(
                OccupancySession.entered_at <= end_at
            )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(OccupancySession.last_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_facts(
        self,
        *,
        journey_id: UUID | None,
        zone_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[OccupancyFact], int]:
        statement = select(OccupancyFact)
        if journey_id is not None:
            statement = statement.where(
                OccupancyFact.journey_id == journey_id
            )
        if zone_id is not None:
            statement = statement.where(
                (OccupancyFact.current_zone_id == zone_id)
                | (OccupancyFact.origin_zone_id == zone_id)
            )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(OccupancyFact.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def summary(self, zone_id: UUID | None) -> dict[str, int]:
        statement = select(
            OccupancySession.state,
            OccupancySession.subject_type,
            func.count(),
        )
        if zone_id is not None:
            statement = statement.where(
                OccupancySession.zone_id == zone_id
            )
        rows = (
            await self.session.execute(
                statement.group_by(
                    OccupancySession.state,
                    OccupancySession.subject_type,
                )
            )
        ).all()
        counts = {
            (state, subject): int(count)
            for state, subject, count in rows
        }
        active = {
            subject: counts.get(
                (OccupancySessionState.ACTIVE, subject), 0
            )
            for subject in OccupancySubjectType
        }
        return {
            "active_total": sum(active.values()),
            "active_employee": active[OccupancySubjectType.EMPLOYEE],
            "active_unknown": active[OccupancySubjectType.UNKNOWN],
            "active_unresolved": active[
                OccupancySubjectType.UNRESOLVED
            ],
            "temporarily_lost": sum(
                count
                for (state, _), count in counts.items()
                if state == OccupancySessionState.TEMPORARILY_LOST
            ),
            "stale": sum(
                count
                for (state, _), count in counts.items()
                if state == OccupancySessionState.STALE
            ),
            "needs_review": sum(
                count
                for (state, _), count in counts.items()
                if state == OccupancySessionState.NEED_REVIEW
            ),
        }
