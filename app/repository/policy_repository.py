"""Persistence for policy configuration, evaluations, and alerts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Camera,
    CaptureEvent,
    JourneyCorrelation,
    OccupancyFact,
    OccupancySession,
    PolicyEvaluation,
    PolicyRule,
    PPEAnalysis,
    SecurityAlert,
    SecurityAlertType,
    SecurityAlertStatus,
    SubjectPolicyProfile,
    Zone,
)


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fact_for_capture(
        self, capture_id: UUID
    ) -> OccupancyFact | None:
        return await self.session.scalar(
            select(OccupancyFact)
            .join(
                JourneyCorrelation,
                JourneyCorrelation.journey_event_id
                == OccupancyFact.journey_event_id,
            )
            .where(JourneyCorrelation.capture_event_id == capture_id)
        )

    async def capture(self, capture_id: UUID) -> CaptureEvent | None:
        return await self.session.get(CaptureEvent, capture_id)

    async def camera(self, camera_id: UUID) -> Camera | None:
        return await self.session.get(Camera, camera_id)

    async def zone(self, zone_id: UUID | None) -> Zone | None:
        return await self.session.get(Zone, zone_id) if zone_id else None

    async def session_for_fact(
        self, fact: OccupancyFact
    ) -> OccupancySession | None:
        return await self.session.scalar(
            select(OccupancySession)
            .where(
                OccupancySession.journey_id == fact.journey_id,
                OccupancySession.zone_id
                == (fact.current_zone_id or fact.origin_zone_id),
            )
            .order_by(OccupancySession.entered_at.desc())
            .limit(1)
        )

    async def ppe(self, capture_id: UUID) -> PPEAnalysis | None:
        return await self.session.scalar(
            select(PPEAnalysis).where(
                PPEAnalysis.capture_event_id == capture_id
            )
        )

    async def profile(
        self, person_id: UUID | None, external_key: str | None
    ) -> SubjectPolicyProfile | None:
        conditions = []
        if person_id:
            conditions.append(SubjectPolicyProfile.person_id == person_id)
        if external_key:
            conditions.append(
                SubjectPolicyProfile.external_subject_key == external_key
            )
        if not conditions:
            return None
        return await self.session.scalar(
            select(SubjectPolicyProfile).where(
                SubjectPolicyProfile.active.is_(True),
                or_(*conditions),
            )
        )

    async def profile_exists(
        self, person_id: UUID | None, external_key: str | None
    ) -> bool:
        conditions = []
        if person_id:
            conditions.append(SubjectPolicyProfile.person_id == person_id)
        if external_key:
            conditions.append(
                SubjectPolicyProfile.external_subject_key == external_key
            )
        if not conditions:
            return False
        return bool(await self.session.scalar(
            select(func.count())
            .select_from(SubjectPolicyProfile)
            .where(or_(*conditions))
        ))

    async def rule_name_exists(self, name: str) -> bool:
        return bool(await self.session.scalar(
            select(func.count())
            .select_from(PolicyRule)
            .where(PolicyRule.name == name)
        ))

    async def rules(self, zone_id: UUID | None) -> list[PolicyRule]:
        return list(
            (
                await self.session.scalars(
                    select(PolicyRule)
                    .where(
                        PolicyRule.enabled.is_(True),
                        or_(
                            PolicyRule.zone_id.is_(None),
                            PolicyRule.zone_id == zone_id,
                        ),
                    )
                    .order_by(PolicyRule.priority, PolicyRule.name)
                )
            ).all()
        )

    async def evaluation(
        self, fact_id: UUID
    ) -> PolicyEvaluation | None:
        return await self.session.scalar(
            select(PolicyEvaluation).where(
                PolicyEvaluation.occupancy_fact_id == fact_id
            )
        )

    async def alert_by_key(self, key: str) -> SecurityAlert | None:
        return await self.session.scalar(
            select(SecurityAlert).where(
                SecurityAlert.deduplication_key == key
            )
        )

    async def active_camera_alert(
        self, camera_id: UUID
    ) -> SecurityAlert | None:
        return await self.session.scalar(
            select(SecurityAlert)
            .where(
                SecurityAlert.camera_id == camera_id,
                SecurityAlert.alert_type
                == SecurityAlertType.CAMERA_OFFLINE,
                SecurityAlert.status.in_([
                    SecurityAlertStatus.OPEN,
                    SecurityAlertStatus.ACKNOWLEDGED,
                ]),
            )
            .order_by(SecurityAlert.occurred_at.desc())
            .limit(1)
        )

    def add(self, entity: Any) -> None:
        self.session.add(entity)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def get_alert(self, alert_id: UUID) -> SecurityAlert | None:
        return await self.session.get(SecurityAlert, alert_id)

    async def list_alerts(
        self, *, status: SecurityAlertStatus | None, zone_id: UUID | None,
        alert_type: Any | None, offset: int, limit: int,
    ) -> tuple[list[SecurityAlert], int]:
        statement = select(SecurityAlert)
        if status:
            statement = statement.where(SecurityAlert.status == status)
        if zone_id:
            statement = statement.where(SecurityAlert.zone_id == zone_id)
        if alert_type:
            statement = statement.where(SecurityAlert.alert_type == alert_type)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(SecurityAlert.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_rules(self) -> list[PolicyRule]:
        return list((await self.session.scalars(
            select(PolicyRule).order_by(PolicyRule.priority, PolicyRule.name)
        )).all())

    async def list_evaluations(
        self, *, offset: int, limit: int
    ) -> tuple[list[PolicyEvaluation], int]:
        statement = select(PolicyEvaluation)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(PolicyEvaluation.evaluated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_profiles(
        self, *, offset: int, limit: int
    ) -> tuple[list[SubjectPolicyProfile], int]:
        statement = select(SubjectPolicyProfile)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(SubjectPolicyProfile.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)
