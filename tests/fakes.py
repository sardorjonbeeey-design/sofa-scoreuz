"""Shared test doubles. No network, no credentials."""

from app.football.provider import FootballProvider


class StubProvider(FootballProvider):
    """A provider whose every call fails loudly unless overridden.

    Tests subclass it and implement only the calls they expect, so an
    unexpected upstream request (which costs real quota) is a failure.
    """

    async def search_teams(self, query):
        raise AssertionError("unexpected search_teams call")

    async def get_team(self, team_id):
        raise AssertionError("unexpected get_team call")

    async def get_team_fixtures(self, *args, **kwargs):
        raise AssertionError("unexpected get_team_fixtures call")

    async def get_live_fixtures(self):
        raise AssertionError("unexpected get_live_fixtures call")

    async def get_fixtures_by_date(self, day, timezone=None):
        raise AssertionError("unexpected get_fixtures_by_date call")

    async def get_leagues(self, *, league_id=None, country=None):
        raise AssertionError("unexpected get_leagues call")

    async def get_standings(self, league_id, season):
        raise AssertionError("unexpected get_standings call")

    async def get_live_events(self, fixture_id):
        raise AssertionError("unexpected get_live_events call")


# --- data builders ---------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from app.football.models import (  # noqa: E402
    Fixture,
    League,
    StandingRow,
    StandingsGroup,
    Team,
)

UTC = timezone.utc


def make_fixture(
    fixture_id: int,
    home: str = "Home FC",
    away: str = "Away FC",
    *,
    home_id: int | None = None,
    away_id: int | None = None,
    status: str = "NS",
    elapsed: int | None = None,
    goals: tuple[int | None, int | None] = (None, None),
    start: datetime | None = None,
    competition: str = "Premier League",
    league_id: int | None = 39,
    country: str | None = "England",
) -> Fixture:
    return Fixture(
        id=fixture_id,
        home_team=Team(home_id or fixture_id * 10 + 1, home),
        away_team=Team(away_id or fixture_id * 10 + 2, away),
        start_time=start or datetime(2026, 10, 26, 12, 30, tzinfo=UTC),
        competition=competition,
        status=status,
        elapsed=elapsed,
        home_goals=goals[0],
        away_goals=goals[1],
        league_id=league_id,
        league_country=country,
    )


def make_table(*names: str, group: str | None = None) -> StandingsGroup:
    rows = tuple(
        StandingRow(
            rank=index,
            team=Team(1000 + index, name),
            played=10,
            won=7,
            drawn=2,
            lost=1,
            goals_for=20,
            goals_against=8,
            goal_diff=12,
            points=23 - index,
        )
        for index, name in enumerate(names, start=1)
    )

    return StandingsGroup(group, rows)


class FakeFootball(StubProvider):
    """Scriptable provider that counts every upstream call."""

    def __init__(self):
        self.live: list[Fixture] = []
        self.by_date: list[Fixture] = []
        self.team_fixtures: list[Fixture] = []
        self.leagues: dict[int, League] = {}
        self.country_leagues: list[League] = []
        self.tables: dict[int, list[StandingsGroup]] = {}
        self.teams: dict[int, Team] = {}
        self.error: Exception | None = None
        self.calls: dict[str, int] = {}

    def _hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

        if self.error is not None:
            raise self.error

    async def get_live_fixtures(self):
        self._hit("live")
        return list(self.live)

    async def get_fixtures_by_date(self, day, timezone=None):
        self._hit("by_date")
        self.last_date = (day, timezone)
        return list(self.by_date)

    async def get_team_fixtures(self, team_id, from_date, to_date):
        self._hit("team_fixtures")
        return list(self.team_fixtures)

    async def get_team(self, team_id):
        self._hit("team")
        return self.teams.get(team_id)

    async def get_leagues(self, *, league_id=None, country=None):
        self._hit("leagues")

        if league_id is not None:
            league = self.leagues.get(league_id)
            return [league] if league else []

        return list(self.country_leagues)

    async def get_standings(self, league_id, season):
        self._hit("standings")
        return list(self.tables.get(league_id, []))
