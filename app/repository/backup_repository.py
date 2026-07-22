from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BackupArchive, BackupSource, BackupStatus
from app.repository.base import BaseRepository


class BackupRepository(BaseRepository[BackupArchive]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, BackupArchive)

    async def get_by_checksum(self, checksum: str) -> BackupArchive | None:
        return await self.session.scalar(
            select(BackupArchive).where(BackupArchive.checksum_sha256 == checksum)
        )

    async def get_automatic_for_date(self, backup_date: date) -> BackupArchive | None:
        return await self.session.scalar(
            select(BackupArchive).where(
                BackupArchive.source == BackupSource.AUTOMATIC,
                BackupArchive.backup_date == backup_date,
            )
        )

    async def list_recent(self, *, offset: int, limit: int) -> tuple[list[BackupArchive], int]:
        total = int(
            await self.session.scalar(select(func.count()).select_from(BackupArchive)) or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(BackupArchive)
                    .order_by(BackupArchive.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return items, total

    async def automatic_older_than(self, cutoff: date) -> list[BackupArchive]:
        return list(
            (
                await self.session.scalars(
                    select(BackupArchive).where(
                        BackupArchive.source == BackupSource.AUTOMATIC,
                        BackupArchive.backup_date < cutoff,
                    )
                )
            ).all()
        )

    async def recover_interrupted(self, *, completed_at: datetime) -> int:
        """Mark jobs left in CREATING by a previous process as failed."""
        result = await self.session.execute(
            update(BackupArchive)
            .where(BackupArchive.status == BackupStatus.CREATING)
            .values(
                status=BackupStatus.FAILED,
                error_message="Recovered an interrupted backup job after restart",
                completed_at=completed_at,
            )
        )
        return int(result.rowcount or 0)
