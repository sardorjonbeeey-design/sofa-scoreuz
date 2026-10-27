"""Versioned, non-destructive schema migrations."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import inspect, Column, DateTime, Integer, MetaData, String, Table, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage.models import Base

logger = logging.getLogger(__name__)
ADVISORY_LOCK_KEY = 720_394_117
_version_metadata = MetaData()
schema_migrations = Table(
    "schema_migrations", _version_metadata,
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
    Base.metadata.create_all(connection, checkfirst=True)


def _add_favorite_team_type(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("favorite_teams")}
    if "team_type" not in columns:
        connection.execute(text("ALTER TABLE favorite_teams ADD COLUMN team_type VARCHAR(12) NOT NULL DEFAULT 'club'"))


def _create_archive_records(connection: Connection) -> None:
    Base.metadata.tables["archive_records"].create(connection, checkfirst=True)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "create users and favorite_teams", _create_initial_tables),
    Migration(2, "add favorite team slot type", _add_favorite_team_type),
    Migration(3, "create persistent football archive", _create_archive_records),
)


def _validate(migrations: tuple[Migration, ...]) -> None:
    versions = [item.version for item in migrations]
    if versions != sorted(set(versions)):
        raise RuntimeError("MIGRATIONS must have unique, ascending version numbers.")


_validate(MIGRATIONS)


async def run_migrations(engine: AsyncEngine, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[int]:
    _validate(migrations)
    applied_now: list[int] = []
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        await connection.run_sync(lambda sync_conn: schema_migrations.create(sync_conn, checkfirst=True))
        result = await connection.execute(select(schema_migrations.c.version))
        already_applied = {row[0] for row in result}
        for migration in migrations:
            if migration.version in already_applied:
                continue
            await connection.run_sync(migration.apply)
            await connection.execute(schema_migrations.insert().values(
                version=migration.version, name=migration.name, applied_at=datetime.now(timezone.utc)
            ))
            applied_now.append(migration.version)
            logger.info("Applied database migration %s: %s", migration.version, migration.name)
    return applied_now
