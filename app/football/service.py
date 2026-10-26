import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.cache.snapshot import Snapshot, SnapshotCache
from app.football.models import (
    Fixture,
    League,
    StandingsGroup,
    Team,
)
from app.football.errors import ProviderError
from app.football.leagues import FEATURED_COUNTRIES, featured_league_ids
from app.football.provider import FootballProvider
from app.football.status import FINISHED_STATUSES, NOT_PLAYED_STATUSES

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Tashkent"

# How many matches a team page shows per section.
TEAM_PAGE_MATCHES = 5
# The single request for a team page covers this many days each way.
TEAM_WINDOW_DAYS = 30


@dataclass(frozen=True)
class CacheTimes:
    """Freshness (seconds) of each kind of data, shared by all users."""

    live: int = 60
    fixtures: int = 300
    standings: int = 30 * 60
    team_fixtures: int = 10 * 60
    country_leagues: int = 12 * 60 * 60

    # How long old data may still be shown when the provider fails.
    # Live scores are never served stale.
    live_max_stale: int = 0
    fixtures_max_stale: int = 60 * 60
    standings_max_stale: int = 24 * 60 * 60
    team_fixtures_max_stale: int = 6 * 60 * 60
    country_leagues_max_stale: int = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class LeagueStandings:
    league: League | None
    season: int | None
    groups: tuple[StandingsGroup, ...]


@dataclass(frozen=True)
class TeamMatches:
    upcoming: tuple[Fixture, ...]
    recent: tuple[Fixture, ...]


class FootballService:
    """Football queries for the bot, with shared, freshness-aware caching.

    Every public method returns a ``Snapshot`` (data + when it was
    fetched + whether it is stale) or raises a ``ProviderError``. The
    underlying cache is shared by all users, so N users asking for the
    same live table cost one provider request per freshness window.
    """

    def __init__(
        self,
        provider: FootballProvider,
        *,
        timezone: str = DEFAULT_TIMEZONE,
        times: CacheTimes | None = None,
        cache: SnapshotCache | None = None,
    ):
        self.provider = provider
        self.times = times or CacheTimes()
        self.cache = cache if cache is not None else SnapshotCache()
        self.timezone_name, self.tz = _load_timezone(timezone)
        self._known_league_ids: set[int] = set()

    # --- existing helpers ------------------------------------------------

    async def search_teams(self, query: str) -> list[Team]:
        return await self.provider.search_teams(query)

    async def team_schedule(
        self,
        team_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Fixture]:
        return await self.provider.get_team_fixtures(
            team_id,
            from_date,
            to_date,
        )

    # --- time ------------------------------------------------------------

    def now_local(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now_local().date()

    # --- queries -----------------------------------------------------------

    async def live_fixtures(self) -> Snapshot[tuple[Fixture, ...]]:
        async def load():
            return tuple(await self.provider.get_live_fixtures())

        return await self.cache.get(
            "fixtures:live",
            load,
            ttl=self.times.live,
            max_stale=self.times.live_max_stale,
        )

    async def todays_fixtures(self) -> Snapshot[tuple[Fixture, ...]]:
        day = self.today()

        async def load():
            return tuple(
                await self.provider.get_fixtures_by_date(
                    day,
                    self.timezone_name,
                )
            )

        return await self.cache.get(
            f"fixtures:{day.isoformat()}:{self.timezone_name}",
            load,
            ttl=self.times.fixtures,
            max_stale=self.times.fixtures_max_stale,
        )

    async def league_standings(
        self,
        league_id: int,
    ) -> Snapshot[LeagueStandings]:
        async def load():
            leagues = await self.provider.get_leagues(league_id=league_id)
            league = leagues[0] if leagues else None

            if league is None or league.current_season is None:
                return LeagueStandings(league, None, ())

            groups = await self.provider.get_standings(
                league_id,
                league.current_season,
            )

            return LeagueStandings(
                league,
                league.current_season,
                tuple(groups),
            )

        return await self.cache.get(
            f"standings:{league_id}",
            load,
            ttl=self.times.standings,
            max_stale=self.times.standings_max_stale,
        )

    async def country_leagues(
        self,
        country: str,
    ) -> Snapshot[tuple[League, ...]]:
        async def load():
            leagues = await self.provider.get_leagues(country=country)

            # Domestic leagues only; cups have no table to show here.
            return tuple(
                league
                for league in leagues
                if (league.type or "").lower() == "league"
            )

        snapshot = await self.cache.get(
            f"leagues:country:{country.lower()}",
            load,
            ttl=self.times.country_leagues,
            max_stale=self.times.country_leagues_max_stale,
        )
        self._known_league_ids.update(
            league.id for league in snapshot.value
        )

        return snapshot

    async def is_known_league(self, league_id: int) -> bool:
        """True only for leagues the bot itself offers to users.

        That is the featured list plus the domestic leagues the provider
        returned for the featured countries. After a restart the second
        group is rebuilt from the (cached) country lookups.
        """
        if league_id in featured_league_ids():
            return True

        if league_id not in self._known_league_ids:
            for country in FEATURED_COUNTRIES:
                try:
                    await self.country_leagues(country.name)
                except ProviderError:
                    continue

        return league_id in self._known_league_ids

    async def team_matches(self, team_id: int) -> Snapshot[TeamMatches]:
        async def load():
            today = self.now_local()
            window = timedelta(days=TEAM_WINDOW_DAYS)
            fixtures = await self.provider.get_team_fixtures(
                team_id,
                today - window,
                today + window,
            )

            return split_team_matches(fixtures)

        return await self.cache.get(
            f"team-fixtures:{team_id}:{self.today().isoformat()}",
            load,
            ttl=self.times.team_fixtures,
            max_stale=self.times.team_fixtures_max_stale,
        )


def split_team_matches(fixtures: list[Fixture]) -> TeamMatches:
    """Next matches (soonest first) and last results (latest first)."""
    finished = sorted(
        (f for f in fixtures if f.status in FINISHED_STATUSES),
        key=lambda f: f.start_time,
        reverse=True,
    )
    upcoming = sorted(
        (
            f
            for f in fixtures
            if f.status not in FINISHED_STATUSES
            and f.status not in NOT_PLAYED_STATUSES
        ),
        key=lambda f: f.start_time,
    )

    return TeamMatches(
        upcoming=tuple(upcoming[:TEAM_PAGE_MATCHES]),
        recent=tuple(finished[:TEAM_PAGE_MATCHES]),
    )


def _load_timezone(name: str) -> tuple[str, tzinfo]:
    try:
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        logger.warning(
            "Unknown or unavailable timezone %r; using %s.",
            name,
            DEFAULT_TIMEZONE,
        )

    try:
        return DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, OSError):
        logger.error(
            "No timezone database found (install the 'tzdata' "
            "package); falling back to UTC."
        )
        return "UTC", dt_timezone.utc
