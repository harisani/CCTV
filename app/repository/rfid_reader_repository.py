from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RFIDReader
from app.repository.base import BaseRepository


class RFIDReaderRepository(BaseRepository[RFIDReader]):
    """Async persistence operations for RFID reader endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RFIDReader)

    async def get_by_code(self, code: str) -> RFIDReader | None:
        return await self.session.scalar(
            select(RFIDReader).where(RFIDReader.code == code.strip())
        )

    async def list_enabled(self) -> list[RFIDReader]:
        statement = (
            select(RFIDReader)
            .where(RFIDReader.enabled.is_(True))
            .order_by(RFIDReader.name, RFIDReader.code)
        )
        return list((await self.session.scalars(statement)).all())
