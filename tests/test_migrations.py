"""Schema migrations: idempotent, non-destructive, atomic."""

import os

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.storage.database import normalize_database_url, prepare_engine_args
from app.storage.migrations import (
    MIGRATIONS,
    Migration,
    run_migrations,
    schema_migrations,
)


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    yield engine
    await engine.dispose()


async def table_names(engine) -> set[str]:
    async with engine.connect() as connection:
        return set(
            await connection.run_sync(
                lambda c: inspect(c).get_table_names()
            )
        )


async def test_creates_tables_and_records_the_version(engine):
    applied = await run_migrations(engine)

    assert applied == [m.version for m in MIGRATIONS]
    assert {"users", "favorite_teams", "schema_migrations"} <= (
        await table_names(engine)
    )

    async with engine.connect() as connection:
        versions = (
            await connection.execute(select(schema_migrations.c.version))
        ).scalars().all()

    assert versions == [m.version for m in MIGRATIONS]


async def test_running_twice_applies_nothing_the_second_time(engine):
    await run_migrations(engine)

    assert await run_migrations(engine) == []


async def test_existing_data_survives_a_rerun(engine):
    await run_migrations(engine)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (telegram_id, language, created_at) "
                "VALUES (42, 'ru', '2026-01-01 00:00:00')"
            )
        )

    await run_migrations(engine)

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT telegram_id, language FROM users")
            )
        ).all()

    assert [tuple(r) for r in rows] == [(42, "ru")]


async def test_database_created_before_versioning_is_adopted(engine):
    # Tables exist (created by an older release) but no version table.
    await run_migrations(engine)

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE schema_migrations"))
        await connection.execute(
            text(
                "INSERT INTO users (telegram_id, language, created_at) "
                "VALUES (7, 'uz', '2026-01-01 00:00:00')"
            )
        )

    assert await run_migrations(engine) == [1, 2]

    async with engine.connect() as connection:
        count = (
            await connection.execute(text("SELECT COUNT(*) FROM users"))
        ).scalar_one()

    assert count == 1


@pytest.fixture
async def postgres_engine():
    """A disposable PostgreSQL database, only if one is configured.

    Set TEST_DATABASE_URL to an EMPTY database whose name contains
    "test". The test tables are dropped before and after the test.
    """
    raw = os.getenv("TEST_DATABASE_URL")

    if not raw:
        pytest.skip("TEST_DATABASE_URL is not set (PostgreSQL test).")

    url, connect_args = prepare_engine_args(normalize_database_url(raw))

    if "test" not in (make_url(url).database or ""):
        pytest.skip("Refusing: the test database name must contain 'test'.")

    engine = create_async_engine(url, connect_args=connect_args)

    async def reset():
        async with engine.begin() as connection:
            for name in (
                "half_done",
                "favorite_teams",
                "users",
                "schema_migrations",
            ):
                await connection.execute(text(f"DROP TABLE IF EXISTS {name}"))

    await reset()
    yield engine
    await reset()
    await engine.dispose()


async def test_a_failing_migration_leaves_nothing_half_applied_postgres(
    postgres_engine,
):
    await run_migrations(postgres_engine)

    def broken(connection):
        Table("half_done", MetaData(), Column("id", Integer)).create(
            connection
        )
        raise RuntimeError("boom")

    migrations = (*MIGRATIONS, Migration(99, "broken", broken))

    with pytest.raises(RuntimeError, match="boom"):
        await run_migrations(postgres_engine, migrations)

    assert "half_done" not in await table_names(postgres_engine)

    async with postgres_engine.connect() as connection:
        versions = (
            await connection.execute(select(schema_migrations.c.version))
        ).scalars().all()

    assert 99 not in versions


async def test_concurrent_runs_apply_each_migration_once_postgres(
    postgres_engine,
):
    import asyncio

    results = await asyncio.gather(
        *[run_migrations(postgres_engine) for _ in range(5)]
    )

    # Exactly one runner applied the migrations; the rest saw them done.
    assert sorted(len(r) for r in results) == [0, 0, 0, 0, len(MIGRATIONS)]


async def test_out_of_order_migrations_are_rejected(engine):
    reversed_order = tuple(
        reversed(
            (*MIGRATIONS, Migration(2, "second", lambda connection: None))
        )
    )

    with pytest.raises(RuntimeError, match="ascending"):
        await run_migrations(engine, reversed_order)
