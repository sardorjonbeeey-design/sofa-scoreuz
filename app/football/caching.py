import asyncio
import logging
from datetime import datetime

from app.cache.cache import MemoryCache
from app.football.models import Fixture, MatchEvent, Team
from app.football.provider import FootballProvider

logger = logging.getLogger(__name__)

# Team metadata (names, ids, logos, countries) changes rarely.
TEAM_SEARCH_TTL_SECONDS = 6 * 60 * 60

# A genuine "no match" is cached briefly so repeated typos do not burn
# API quota, but a newly added team can still be found soon after.
EMPTY_SEARCH_TTL_SECONDS = 10 * 60


def search_cache_key(query: str) -> str:
    normalized = " ".join(query.lower().split())
    return f"teams:search:{normalized}"


class CachingFootballProvider(FootballProvider):
    """Adds caching and request de-duplication around a provider.

    * Only team *search* results are cached (stable metadata).
    * Fixtures and live events are deliberately NOT cached here, so a
      live score can never be served stale as if it were current.
    * Provider errors are never cached.
    * Concurrent identical searches share one upstream request.
    """

    def __init__(
        self,
        inner: FootballProvider,
        cache: MemoryCache | None = None,
        search_ttl: int = TEAM_SEARCH_TTL_SECONDS,
        empty_ttl: int = EMPTY_SEARCH_TTL_SECONDS,
    ):
        self.inner = inner
        self.cache = cache if cache is not None else MemoryCache()
        self.search_ttl = search_ttl
        self.empty_ttl = empty_ttl
        self._inflight: dict[str, asyncio.Future] = {}

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)

        if close is not None:
            await close()

    async def search_teams(self, query: str) -> list[Team]:
        key = search_cache_key(query)

        cached = await self.cache.get(key)

        if cached is not None:
            return list(cached)

        task = self._inflight.get(key)

        if task is None:
            task = asyncio.ensure_future(
                self._search_and_store(key, query)
            )
            self._inflight[key] = task
            task.add_done_callback(
                lambda finished, k=key: self._forget(k, finished)
            )

        # shield(): one waiter being cancelled must not cancel the
        # upstream request other waiters are sharing.
        return list(await asyncio.shield(task))

    def _forget(self, key: str, finished: asyncio.Future) -> None:
        if self._inflight.get(key) is finished:
            self._inflight.pop(key, None)

        # Mark the exception as retrieved so no "never retrieved"
        # warning appears when every waiter was cancelled.
        if not finished.cancelled():
            finished.exception()

    async def _search_and_store(
        self,
        key: str,
        query: str,
    ) -> tuple[Team, ...]:
        teams = tuple(await self.inner.search_teams(query))

        await self.cache.set(
            key,
            teams,
            self.search_ttl if teams else self.empty_ttl,
        )

        return teams

    async def get_team_fixtures(
        self,
        team_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Fixture]:
        return await self.inner.get_team_fixtures(
            team_id,
            from_date,
            to_date,
        )

    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:
        return await self.inner.get_live_events(fixture_id)
