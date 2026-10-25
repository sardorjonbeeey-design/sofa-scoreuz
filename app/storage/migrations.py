"""Versioned, non-destructive schema migrations.

Applied migrations are recorded in the ``schema_migrations`` table, so
every migration runs exactly once per database. Nothing here ever drops
tables or data.

To change the schema later:

1. Change the model in ``app/storage/models.py``.
2. Append a new ``Migration`` with the next version number to
   ``MIGRATIONS`` that performs the matching ``ALTER``/``CREATE``.
3. Never edit or reorder a migration that has already been released.

On PostgreSQL a transaction-scoped advisory lock serialises concurrent
runs (for example two instances overlapping during a deploy). Because
PostgreSQL DDL is transactional and the whole run is one transaction, a
failing migration leaves nothing half-applied. SQLite (local development
and tests only) auto-commits DDL, so it does not give that guarantee.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    select,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage.models import Base

logger = logging.getLogger(__name__)

# Arbitrary constant identifying "Flash Football schema migration".
ADVISORY_LOCK_KEY = 720_394_117

_version_metadata = MetaData()

schema_migrations = Table(
    "schema_migrations",
    _version_metadata,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("name", String(200), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def _create_initial_tables(connection: Connection) -> None:
    # checkfirst=True: tables that already exist are left untouched.
    Base.metadata.create_all(connection, checkfirst=True)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create users and favorite_teams",
        apply=_create_initial_tables,
    ),
)


def _validate(migrations: tuple[Migration, ...]) -> None:
    versions = [item.version for item in migrations]

    if versions != sorted(set(versions)):
        raise RuntimeError(
            "MIGRATIONS must have unique, ascending version numbers."
        )


_validate(MIGRATIONS)


async def run_migrations(
    engine: AsyncEngine,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> list[int]:
    """Apply pending migrations. Returns the versions applied now."""
    _validate(migrations)

    applied_now: list[int] = []

    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": ADVISORY_LOCK_KEY},
            )

        await connection.run_sync(
            lambda sync_conn: schema_migrations.create(
                sync_conn,
                checkfirst=True,
            )
        )

        result = await connection.execute(
            select(schema_migrations.c.version)
        )
        already_applied = {row[0] for row in result}

        for migration in migrations:
            if migration.version in already_applied:
                continue

            await connection.run_sync(migration.apply)
            await connection.execute(
                schema_migrations.insert().values(
                    version=migration.version,
                    name=migration.name,
                    applied_at=datetime.now(timezone.utc),
                )
            )
            applied_now.append(migration.version)

            logger.info(
                "Applied database migration %s: %s",
                migration.version,
                migration.name,
            )

    return applied_now
