from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class HealthService:
    """Probe bounded database availability for health endpoints."""

    async def database_ready(
        self,
        session: AsyncSession,
        timeout_seconds: float,
    ) -> bool:
        try:
            async with asyncio.timeout(timeout_seconds):
                await session.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError, TimeoutError):
            return False
        return True
