from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.storage.models import Base


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]

    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]

    return url


def create_session_factory(database_url: str):
    engine = create_async_engine(
        normalize_database_url(database_url)
    )

    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_tables(database_url: str) -> None:
    engine = create_async_engine(
        normalize_database_url(database_url)
    )

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )

    await engine.dispose()