from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DisasterRecoveryArchive, DisasterRecoveryStatus
from app.repository.base import BaseRepository


class DisasterRecoveryRepository(BaseRepository[DisasterRecoveryArchive]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DisasterRecoveryArchive)

    async def get_by_schedule_key(self, key: str) -> DisasterRecoveryArchive | None:
        return await self.session.scalar(
            select(DisasterRecoveryArchive).where(
                DisasterRecoveryArchive.schedule_key == key
            )
        )

    async def get_by_checksum(self, checksum: str) -> DisasterRecoveryArchive | None:
        return await self.session.scalar(
            select(DisasterRecoveryArchive).where(
                DisasterRecoveryArchive.checksum_sha256 == checksum
            )
        )

    async def list_recent(
        self, *, offset: int, limit: int
    ) -> tuple[list[DisasterRecoveryArchive], int]:
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(DisasterRecoveryArchive)
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(DisasterRecoveryArchive)
                    .order_by(DisasterRecoveryArchive.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return items, total

    async def ready_older_than(self, cutoff: datetime) -> list[DisasterRecoveryArchive]:
        return list(
            (
                await self.session.scalars(
                    select(DisasterRecoveryArchive).where(
                        DisasterRecoveryArchive.created_at < cutoff,
                        DisasterRecoveryArchive.status.in_(
                            [
                                DisasterRecoveryStatus.READY,
                                DisasterRecoveryStatus.RESTORED,
                                DisasterRecoveryStatus.FAILED,
                            ]
                        ),
                    )
                )
            ).all()
        )

    async def recover_interrupted(self, *, completed_at: datetime) -> int:
        result = await self.session.execute(
            update(DisasterRecoveryArchive)
            .where(
                DisasterRecoveryArchive.status.in_(
                    [
                        DisasterRecoveryStatus.CREATING,
                        DisasterRecoveryStatus.RESTORING,
                    ]
                )
            )
            .values(
                status=DisasterRecoveryStatus.FAILED,
                error_message="Recovered an interrupted disaster-recovery job",
                completed_at=completed_at,
            )
        )
        return int(result.rowcount or 0)
