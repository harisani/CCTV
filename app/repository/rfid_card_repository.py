from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Employee, RFIDCard, RFIDCardStatus
from app.repository.base import BaseRepository


class RFIDCardRepository(BaseRepository[RFIDCard]):
    """Async persistence operations for physical RFID credentials."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RFIDCard)

    async def get_by_card_number(self, card_number: str) -> RFIDCard | None:
        return await self.session.scalar(
            select(RFIDCard).where(RFIDCard.card_number == card_number.strip().upper())
        )

    async def get_active_by_card_number(
        self,
        card_number: str,
        *,
        at: datetime | None = None,
    ) -> RFIDCard | None:
        checked_at = at or datetime.now(UTC)
        statement = (
            select(RFIDCard)
            .join(Employee, Employee.id == RFIDCard.employee_id)
            .where(
                RFIDCard.card_number == card_number.strip().upper(),
                RFIDCard.status == RFIDCardStatus.ACTIVE,
                Employee.is_active.is_(True),
                or_(RFIDCard.valid_from.is_(None), RFIDCard.valid_from <= checked_at),
                or_(RFIDCard.valid_until.is_(None), RFIDCard.valid_until >= checked_at),
            )
        )
        return await self.session.scalar(statement)

    async def list_by_employee(self, employee_id: UUID) -> list[RFIDCard]:
        statement = (
            select(RFIDCard)
            .where(RFIDCard.employee_id == employee_id)
            .order_by(RFIDCard.created_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def list_by_employee_filtered(
        self,
        employee_id: UUID,
        *,
        card_status: RFIDCardStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[RFIDCard], int]:
        statement = select(RFIDCard).where(RFIDCard.employee_id == employee_id)
        if card_status is not None:
            statement = statement.where(RFIDCard.status == card_status)
        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        page = (
            statement.order_by(RFIDCard.created_at.desc(), RFIDCard.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), total

    async def list_active_with_employees(
        self,
        *,
        at: datetime | None = None,
        limit: int = 200,
    ) -> list[RFIDCard]:
        """Return credentials that can produce a pending access event now."""
        checked_at = at or datetime.now(UTC)
        statement = (
            select(RFIDCard)
            .join(Employee, Employee.id == RFIDCard.employee_id)
            .options(selectinload(RFIDCard.employee))
            .where(
                RFIDCard.status == RFIDCardStatus.ACTIVE,
                Employee.is_active.is_(True),
                or_(RFIDCard.valid_from.is_(None), RFIDCard.valid_from <= checked_at),
                or_(RFIDCard.valid_until.is_(None), RFIDCard.valid_until >= checked_at),
            )
            .order_by(Employee.full_name, Employee.employee_number, RFIDCard.card_number)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())
