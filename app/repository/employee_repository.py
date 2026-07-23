from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee
from app.repository.base import BaseRepository


class EmployeeRepository(BaseRepository[Employee]):
    """Async persistence operations for monitored employees."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Employee)

    async def get_by_employee_number(self, employee_number: str) -> Employee | None:
        normalized = employee_number.strip().casefold()
        return await self.session.scalar(
            select(Employee).where(func.lower(Employee.employee_number) == normalized)
        )

    async def list_filtered(
        self,
        *,
        search: str | None = None,
        department: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Employee], int]:
        statement = select(Employee)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Employee.employee_number.ilike(pattern),
                    Employee.full_name.ilike(pattern),
                )
            )
        if department:
            statement = statement.where(
                func.lower(Employee.department) == department.strip().casefold()
            )
        if is_active is not None:
            statement = statement.where(Employee.is_active.is_(is_active))

        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        page = (
            statement.order_by(Employee.full_name, Employee.employee_number)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), total

    async def list_by_ids(self, employee_ids: list[UUID]) -> list[Employee]:
        if not employee_ids:
            return []
        statement = select(Employee).where(Employee.id.in_(employee_ids))
        return list((await self.session.scalars(statement)).all())

    async def get_by_employee_numbers(
        self,
        employee_numbers: list[str],
    ) -> list[Employee]:
        normalized = [value.strip().lower() for value in employee_numbers if value.strip()]
        if not normalized:
            return []
        statement = select(Employee).where(
            func.lower(Employee.employee_number).in_(normalized)
        )
        return list((await self.session.scalars(statement)).all())
