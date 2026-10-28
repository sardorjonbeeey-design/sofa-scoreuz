from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    logo_url: str | None = None
    country: str | None = None
    code: str | None = None
    national: bool = False
    founded: int | None = None
    venue_name: str | None = None
    venue_city: str | None = None
    venue_capacity: int | None = None


@dataclass(frozen=True)
class SquadPlayer:
    id: int
    name: str
    age: int | None = None
    number: int | None = None
    position: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True)
class Fixture:
    id: int
    home_team: Team
    away_team: Team
    start_time: datetime
    competition: str
    venue: str | None = None
    # Provider status code (NS, 1H, HT, 2H, FT, ...); NS = not started.
    status: str = "NS"
    elapsed: int | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    league_id: int | None = None
    league_country: str | None = None


@dataclass(frozen=True)
class League:
    id: int
    name: str
    country: str | None = None
    type: str | None = None
    logo_url: str | None = None
    current_season: int | None = None


@dataclass(frozen=True)
class StandingRow:
    rank: int
    team: Team
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    form: str | None = None


@dataclass(frozen=True)
class StandingsGroup:
    """One table. Cups with a group stage return several groups."""

    name: str | None
    rows: tuple[StandingRow, ...]


@dataclass(frozen=True)
class MatchEvent:
    fixture_id: int
    event_id: str
    minute: int | None
    event_type: str
    team_id: int | None
    player_name: str | None = None
