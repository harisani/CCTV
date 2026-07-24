from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import get_settings

settings = get_settings()
engine = create_async_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    echo=settings.debug,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one request session and roll back any escaping failure."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
