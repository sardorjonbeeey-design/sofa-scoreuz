"""User preference storage used by the bot handlers.

Two interchangeable implementations share one interface:

* ``SqlPreferenceStore``    - PostgreSQL (or any SQLAlchemy async DB).
* ``MemoryPreferenceStore`` - NON-persistent, for local development and
  tests, or when no DATABASE_URL is configured.

Every write either succeeds or raises ``StorageError``; nothing is
ever reported as saved when it was not.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.localization.i18n import DEFAULT_LANGUAGE, normalize_language
from app.storage.database import (
    Database,
    StorageError,
    describe_db_error,
)
from app.storage.repository import (
    FavoriteTeamRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

TEAM_NAME_MAX_LENGTH = 150


class AddFavoriteResult(str, Enum):
    ADDED = "added"
    DUPLICATE = "duplicate"
    LIMIT_REACHED = "limit_reached"


@dataclass(frozen=True)
class FavoriteTeamRecord:
    team_id: int
    team_name: str
    team_type: str = "club"


class PreferenceStore(Protocol):

    async def get_language(self, telegram_id: int) -> str | None: ...

    async def set_language(
        self,
        telegram_id: int,
        language: str,
    ) -> None: ...

    async def list_favorites(
        self,
        telegram_id: int,
    ) -> list[FavoriteTeamRecord]: ...

    async def add_favorite(
        self,
        telegram_id: int,
        team_id: int,
        team_name: str,
        limit: int,
        team_type: str | None = None,
    ) -> AddFavoriteResult: ...
    async def remove_favorite(
        self,
        telegram_id: int,
        team_id: int,
    ) -> bool: ...

    async def close(self) -> None: ...


class MemoryPreferenceStore:
    """Process-local store. Data is lost on restart."""

    persistent = False

    def __init__(self, default_language: str = DEFAULT_LANGUAGE):
        self.default_language = normalize_language(default_language)
        self._languages: dict[int, str] = {}
        self._favorites: dict[int, list[FavoriteTeamRecord]] = {}

    async def get_language(self, telegram_id: int) -> str | None:
        return self._languages.get(telegram_id)

    async def set_language(
        self,
        telegram_id: int,
        language: str,
    ) -> None:
        self._languages[telegram_id] = normalize_language(
            language,
            self.default_language,
        )

    async def list_favorites(
        self,
        telegram_id: int,
    ) -> list[FavoriteTeamRecord]:
        return list(self._favorites.get(telegram_id, []))

    async def add_favorite(
        self,
        telegram_id: int,
        team_id: int,
        team_name: str,
        limit: int,
        team_type: str | None = None,
    ) -> AddFavoriteResult:
        favorites = self._favorites.setdefault(telegram_id, [])

        if any(item.team_id == team_id for item in favorites):
            return AddFavoriteResult.DUPLICATE

        if team_type is not None:
            if any(item.team_type == team_type for item in favorites):
                return AddFavoriteResult.LIMIT_REACHED
        elif len(favorites) >= limit:
            return AddFavoriteResult.LIMIT_REACHED

        favorites.append(
            FavoriteTeamRecord(
                team_id=team_id,
                team_name=team_name[:TEAM_NAME_MAX_LENGTH],
                team_type=team_type or "club",
            )
        )

        return AddFavoriteResult.ADDED

    async def remove_favorite(
        self,
        telegram_id: int,
        team_id: int,
    ) -> bool:
        favorites = self._favorites.get(telegram_id, [])
        remaining = [i for i in favorites if i.team_id != team_id]

        self._favorites[telegram_id] = remaining

        return len(remaining) != len(favorites)

    async def close(self) -> None:
        return None


class SqlPreferenceStore:
    """Database-backed store built on the existing repositories."""

    persistent = True

    # Per-user serialisation of "check limit, then insert" using a
    # fixed number of locks, so memory use stays bounded.
    _LOCK_STRIPES = 64

    def __init__(
        self,
        database: Database,
        default_language: str = DEFAULT_LANGUAGE,
    ):
        self.database = database
        self.default_language = normalize_language(default_language)
        self._locks = [
            asyncio.Lock() for _ in range(self._LOCK_STRIPES)
        ]

    def _lock_for(self, telegram_id: int) -> asyncio.Lock:
        return self._locks[telegram_id % self._LOCK_STRIPES]

    @asynccontextmanager
    async def _session(self, operation: str):
        await self.database.ensure_schema()

        try:
            async with self.database.session_factory() as session:
                yield session
        except (SQLAlchemyError, OSError, asyncio.TimeoutError) as exc:
            logger.error(
                "Database operation '%s' failed (%s): %s",
                operation,
                type(exc).__name__,
                describe_db_error(exc),
            )
            raise StorageError(
                f"Database operation '{operation}' failed."
            ) from exc

    async def get_language(self, telegram_id: int) -> str | None:
        async with self._session("get_language") as session:
            user = await UserRepository(
                session
            ).get_by_telegram_id(telegram_id)

            return user.language if user else None

    async def set_language(
        self,
        telegram_id: int,
        language: str,
    ) -> None:
        language = normalize_language(language, self.default_language)

        async with self._session("set_language") as session:
            await UserRepository(session).set_language(
                telegram_id,
                language,
            )

    async def list_favorites(
        self,
        telegram_id: int,
    ) -> list[FavoriteTeamRecord]:
        async with self._session("list_favorites") as session:
            user = await UserRepository(
                session
            ).get_by_telegram_id(telegram_id)

            if user is None:
                return []

            rows = await FavoriteTeamRepository(
                session
            ).list_for_user(user.id)

            return [
                FavoriteTeamRecord(
                    team_id=row.team_id,
                    team_name=row.team_name,
                    team_type=row.team_type,
                )
                for row in rows
            ]

    async def add_favorite(
        self,
        telegram_id: int,
        team_id: int,
        team_name: str,
        limit: int,
        team_type: str | None = None,
    ) -> AddFavoriteResult:
        async with self._lock_for(telegram_id):
            async with self._session("add_favorite") as session:
                user = await UserRepository(session).get_or_create(
                    telegram_id,
                    self.default_language,
                )
                favorites = FavoriteTeamRepository(session)

                # Duplicate check first, so re-adding an existing
                # favorite is reported as such even at the limit.
                if await favorites.exists(user.id, team_id):
                    return AddFavoriteResult.DUPLICATE

                existing = await favorites.list_for_user(user.id)
                if team_type is not None:
                    if any(row.team_type == team_type for row in existing):
                        return AddFavoriteResult.LIMIT_REACHED
                elif len(existing) >= limit:
                    return AddFavoriteResult.LIMIT_REACHED

                try:
                    await favorites.add(
                        user.id,
                        team_id,
                        team_name[:TEAM_NAME_MAX_LENGTH],
                        team_type or "club",
                    )
                except IntegrityError:
                    # Lost a race with an identical request.
                    await session.rollback()
                    return AddFavoriteResult.DUPLICATE

                return AddFavoriteResult.ADDED

    async def remove_favorite(
        self,
        telegram_id: int,
        team_id: int,
    ) -> bool:
        async with self._lock_for(telegram_id):
            async with self._session("remove_favorite") as session:
                user = await UserRepository(
                    session
                ).get_by_telegram_id(telegram_id)

                if user is None:
                    return False

                return await FavoriteTeamRepository(
                    session
                ).remove(user.id, team_id)

    async def close(self) -> None:
        await self.database.dispose()
