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


# --- archive test double ---------------------------------------------------

from datetime import timezone as _timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def standings_archive_payload(league_id=39, league_name="Premier League", teams=None):
    """A source-attributed structured table for tests; never used in production."""
    teams = teams or ["Arsenal", "Chelsea", "Liverpool", "City", "United", "Spurs"]
    rows = []
    for position, team in enumerate(teams, start=1):
        rows.append({
            "position": position, "team": team, "played": 10, "won": 7,
            "drawn": 2, "lost": 1, "goals_for": 20, "goals_against": 8,
            "goal_difference": 12, "points": 23 - position + 1,
        })
    return {
        "league_id": league_id,
        "league_name": league_name,
        "queried_at": "2026-10-27T20:00:00+00:00",
        "parser_version": 2,
        "results": [{
            "title": f"{league_name} Table",
            "url": "https://www.espn.com/soccer/standings",
            "snippet": "Current league standings",
        }],
        "table": {
            "league_id": league_id,
            "league_name": league_name,
            "season": 2026,
            "rows": rows,
            "source_url": "https://www.espn.com/soccer/standings",
            "source_title": f"{league_name} Table",
            "retrieved_at": "2026-10-27T20:00:00+00:00",
            "verified_structure": True,
        },
        "data_type": "structured_standings",
    }


class FakeArchive:
    """Small in-memory archive for UI/service tests."""
    def __init__(self, payloads=None):
        self.records = {
            ("tinyfish_standings", str(key)): value
            for key, value in (payloads or {}).items()
        }
        self.reads = 0
        self.writes = 0

    async def get(self, *, kind, record_key, max_age_seconds=None):
        self.reads += 1
        payload = self.records.get((kind, str(record_key)))
        if payload is None:
            return None
        return SimpleNamespace(payload=payload, fetched_at=datetime.now(_timezone.utc))

    async def upsert(self, *, kind, record_key, payload, source="test"):
        self.writes += 1
        self.records[(kind, str(record_key))] = payload
        return SimpleNamespace(payload=payload, fetched_at=datetime.now(_timezone.utc))
