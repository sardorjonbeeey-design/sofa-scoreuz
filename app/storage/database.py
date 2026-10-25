import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.storage.migrations import run_migrations

logger = logging.getLogger(__name__)

_SSL_MODES = {
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
}


class DatabaseConfigError(Exception):
    """DATABASE_URL cannot be used.

    The message never contains the URL, because it carries the
    database password.
    """


class StorageError(Exception):
    """A storage operation failed and nothing was (or can be assumed
    to be) saved. Callers must tell the user and must not pretend the
    write succeeded."""


def _unique_statement_name() -> str:
    # Behind PgBouncer in transaction mode, asyncpg's default numbered
    # statement names collide across pooled connections.
    return f"__asyncpg_{uuid.uuid4()}__"


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]

    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]

    return url


def prepare_engine_args(database_url: str) -> tuple[URL, dict[str, Any]]:
    """Return ``(url, connect_args)`` ready for ``create_async_engine``.

    * ``postgres://`` / ``postgresql://`` become ``postgresql+asyncpg://``.
    * A libpq-style ``?sslmode=...`` is translated to asyncpg's ``ssl``
      argument, because asyncpg rejects ``sslmode``.
    * Prepared-statement caching is disabled so the same URL also works
      through PgBouncer in transaction mode (Supabase pooler).
    * Connect/command timeouts keep a dead database from hanging the bot.
    """
    try:
        url = make_url(normalize_database_url(database_url.strip()))
    except (ArgumentError, ValueError):
        raise DatabaseConfigError(
            "DATABASE_URL is not a valid database URL."
        ) from None

    connect_args: dict[str, Any] = {}

    if url.drivername.startswith("postgresql+asyncpg"):
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)

        if sslmode is not None:
            if isinstance(sslmode, tuple):
                sslmode = sslmode[-1]

            if sslmode in _SSL_MODES:
                connect_args["ssl"] = sslmode

            url = url.set(query=query)

        connect_args.update(
            {
                "statement_cache_size": 0,
                "prepared_statement_name_func": _unique_statement_name,
                "timeout": 10,
                "command_timeout": 20,
            }
        )

        url = url.update_query_dict(
            {"prepared_statement_cache_size": "0"}
        )

    return url, connect_args


class Database:
    """Owns the async engine and the (lazy) schema initialisation."""

    def __init__(self, database_url: str):
        url, connect_args = prepare_engine_args(database_url)

        self.engine: AsyncEngine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Apply pending schema migrations (see ``migrations.py``).

        Never drops data. Safe to call repeatedly and from several
        instances at once: applied versions are recorded and, on
        PostgreSQL, concurrent runs are serialised by an advisory lock.
        """
        if self._schema_ready:
            return

        async with self._schema_lock:
            if self._schema_ready:
                return

            try:
                await run_migrations(self.engine)
            except (SQLAlchemyError, OSError, asyncio.TimeoutError) as exc:
                logger.error(
                    "Could not initialise the database schema (%s): %s",
                    type(exc).__name__,
                    describe_db_error(exc),
                )
                raise StorageError(
                    "Database is not available."
                ) from exc

            self._schema_ready = True
            logger.info("Database schema is ready.")

    async def dispose(self) -> None:
        await self.engine.dispose()


def describe_db_error(exc: BaseException) -> str:
    """Short, SQL-free description that is safe to log."""
    original = getattr(exc, "orig", None) or exc
    return str(original).replace("\n", " ")[:200]


# --- backwards-compatible helpers -------------------------------------


def create_session_factory(database_url: str):
    return Database(database_url).session_factory


async def create_tables(database_url: str) -> None:
    database = Database(database_url)

    try:
        await database.ensure_schema()
    finally:
        await database.dispose()
