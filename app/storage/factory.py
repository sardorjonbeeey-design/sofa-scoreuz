import logging

from app.config import Settings
from app.storage.database import (
    Database,
    DatabaseConfigError,
    StorageError,
)
from app.storage.store import (
    MemoryPreferenceStore,
    PreferenceStore,
    SqlPreferenceStore,
)

logger = logging.getLogger(__name__)


class DatabaseRequiredError(RuntimeError):
    """REQUIRE_DATABASE is set but DATABASE_URL is missing."""


async def create_store(settings: Settings) -> PreferenceStore:
    """Build the preference store for the current configuration.

    * No DATABASE_URL: non-persistent in-memory store (local dev),
      announced loudly. With REQUIRE_DATABASE=true this is an error.
    * DATABASE_URL set: PostgreSQL store. If the database cannot be
      reached right now, the bot still starts; storage operations fail
      visibly (and are retried) until the database is back.
    * Malformed DATABASE_URL: fail fast, without printing the URL.
    """
    if not settings.database_url:
        if settings.require_database:
            raise DatabaseRequiredError(
                "REQUIRE_DATABASE is enabled but DATABASE_URL is not set."
            )

        logger.warning(
            "DATABASE_URL is not set: favorites and language are kept "
            "in memory only and will be LOST on restart."
        )
        return MemoryPreferenceStore(settings.default_language)

    try:
        database = Database(settings.database_url)
    except DatabaseConfigError:
        logger.error(
            "DATABASE_URL is set but is not a valid database URL."
        )
        raise

    store = SqlPreferenceStore(database, settings.default_language)

    try:
        await database.ensure_schema()
    except StorageError:
        logger.error(
            "Database is unreachable at startup. The bot will keep "
            "running; saving data fails (and is retried) until the "
            "database is available."
        )

    return store
