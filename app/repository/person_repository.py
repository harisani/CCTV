from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person
from app.repository.base import BaseRepository


class PersonRepository(BaseRepository[Person]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Person)

    async def get_by_reid_key(self, reid_key: str) -> Person | None:
        return await self.session.scalar(select(Person).where(Person.reid_key == reid_key))

    async def list_with_embeddings(self) -> list[Person]:
        statement = select(Person).where(Person.reid_embedding.is_not(None))
        return list((await self.session.scalars(statement)).all())

    async def list_filtered(self, *, name: str | None, offset: int, limit: int) -> tuple[list[Person], int]:
        from sqlalchemy import func

        statement = select(Person)
        if name:
            statement = statement.where(
                (Person.display_name.ilike(f"%{name}%")) | (Person.reid_key.ilike(f"%{name}%"))
            )
        items = list((await self.session.scalars(statement.order_by(Person.last_seen_at.desc()).offset(offset).limit(limit))).all())
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        return items, total or 0
