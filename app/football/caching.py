import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from app.cache.cache import MemoryCache
from app.football.models import (
    Fixture,
    League,
    MatchEvent,
    SquadPlayer,
    StandingsGroup,
    Team,
)
from app.football.provider import FootballProvider

logger = logging.getLogger(__name__)

# Team metadata (names, ids, logos, countries) changes rarely.
TEAM_SEARCH_TTL_SECONDS = 6 * 60 * 60
TEAM_TTL_SECONDS = 24 * 60 * 60

# League metadata (name, current season) changes about once a year.
LEAGUE_TTL_SECONDS = 12 * 60 * 60

# A genuine "no match" is cached briefly so repeated typos do not burn
# API quota, but a newly added team can still be found soon after.
EMPTY_SEARCH_TTL_SECONDS = 10 * 60


def search_cache_key(query: str) -> str:
    normalized = " ".join(query.lower().split())
    return f"teams:search:{normalized}"


class CachingFootballProvider(FootballProvider):
    """Adds caching and request de-duplication around a provider.

    * Only STABLE data is cached here: team search, team details and
      league metadata.
    * Time-sensitive data (live matches, fixtures, standings) is passed
      straight through; ``FootballService`` caches it with explicit
      freshness so a live score is never served as if it were current.
    * Provider errors are never cached.
    * Concurrent identical requests share one upstream request.
    """

    def __init__(
        self,
        inner: FootballProvider,
        cache: MemoryCache | None = None,
        search_ttl: int = TEAM_SEARCH_TTL_SECONDS,
        empty_ttl: int = EMPTY_SEARCH_TTL_SECONDS,
        team_ttl: int = TEAM_TTL_SECONDS,
        league_ttl: int = LEAGUE_TTL_SECONDS,
    ):
        self.inner = inner
        self.cache = cache if cache is not None else MemoryCache()
        self.search_ttl = search_ttl
        self.empty_ttl = empty_ttl
        self.team_ttl = team_ttl
        self.league_ttl = league_ttl
        self._inflight: dict[str, asyncio.Future] = {}

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)

        if close is not None:
            await close()

    async def _cached(
        self,
        key: str,
        load: Callable[[], Awaitable],
        ttl_for: Callable[[object], int],
    ):
        """Return the cached value for ``key`` or load it once.

        ``None`` is never cached (it is the cache's "miss" marker), so
        callers wrap "nothing found" results in a tuple.
        """
        cached = await self.cache.get(key)

        if cached is not None:
            return cached

        task = self._inflight.get(key)

        if task is None:
            task = asyncio.ensure_future(
                self._load_and_store(key, load, ttl_for)
            )
            self._inflight[key] = task
            task.add_done_callback(
                lambda finished, k=key: self._forget(k, finished)
            )

        # shield(): one waiter being cancelled must not cancel the
        # upstream request other waiters are sharing.
        return await asyncio.shield(task)

    def _forget(self, key: str, finished: asyncio.Future) -> None:
        if self._inflight.get(key) is finished:
            self._inflight.pop(key, None)

        # Mark the exception as retrieved so no "never retrieved"
        # warning appears when every waiter was cancelled.
        if not finished.cancelled():
            finished.exception()

    async def _load_and_store(self, key, load, ttl_for):
        value = await load()

        await self.cache.set(key, value, ttl_for(value))

        return value

    async def search_teams(self, query: str) -> list[Team]:
        teams = await self._cached(
            search_cache_key(query),
            lambda: self._search(query),
            lambda found: self.search_ttl if found else self.empty_ttl,
        )

        return list(teams)

    async def _search(self, query: str) -> tuple[Team, ...]:
        return tuple(await self.inner.search_teams(query))

    async def get_team(self, team_id: int) -> Team | None:
        found = await self._cached(
            f"teams:id:{team_id}",
            lambda: self._one_team(team_id),
            lambda value: self.team_ttl if value else self.empty_ttl,
        )

        return found[0] if found else None

    async def _one_team(self, team_id: int) -> tuple[Team, ...]:
        team = await self.inner.get_team(team_id)

        return (team,) if team else ()

    async def get_leagues(
        self,
        *,
        league_id: int | None = None,
        country: str | None = None,
    ) -> list[League]:
        key = f"leagues:{league_id or ''}:{(country or '').lower()}"

        leagues = await self._cached(
            key,
            lambda: self._leagues(league_id, country),
            lambda value: self.league_ttl if value else self.empty_ttl,
        )

        return list(leagues)

    async def _leagues(self, league_id, country) -> tuple[League, ...]:
        return tuple(
            await self.inner.get_leagues(
                league_id=league_id,
                country=country,
            )
        )

    async def get_team_squad(self, team_id: int) -> list[SquadPlayer]:
        getter = getattr(self.inner, "get_team_squad", None)
        if getter is None:
            return []
        return await getter(team_id)

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

    async def get_live_fixtures(self) -> list[Fixture]:
        return await self.inner.get_live_fixtures()

    async def get_fixtures_by_date(
        self,
        day: date,
        timezone: str | None = None,
    ) -> list[Fixture]:
        return await self.inner.get_fixtures_by_date(day, timezone)

    async def get_standings(
        self,
        league_id: int,
        season: int,
    ) -> list[StandingsGroup]:
        return await self.inner.get_standings(league_id, season)

    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:
        return await self.inner.get_live_events(fixture_id)
