from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from app.repository.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_username(self, username: str) -> User | None:
        return await self.session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))

    async def list_filtered(
        self,
        *,
        search: str | None,
        role: UserRole | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[User], int]:
        statement = select(User)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(or_(User.username.ilike(pattern), User.full_name.ilike(pattern)))
        if role is not None:
            statement = statement.where(User.role == role)
        if is_active is not None:
            statement = statement.where(User.is_active.is_(is_active))
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        page = statement.order_by(User.full_name, User.username).offset(offset).limit(limit)
        return list((await self.session.scalars(page)).all()), total or 0

    async def count_active_super_admins(self, *, excluding: UUID | None = None) -> int:
        statement = select(func.count()).select_from(User).where(
            User.role == UserRole.SUPER_ADMIN,
            User.is_active.is_(True),
        )
        if excluding is not None:
            statement = statement.where(User.id != excluding)
        return int(await self.session.scalar(statement) or 0)
