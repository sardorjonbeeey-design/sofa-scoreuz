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


@dataclass(frozen=True)
class Fixture:
    id: int
    home_team: Team
    away_team: Team
    start_time: datetime
    competition: str
    venue: str | None = None


@dataclass(frozen=True)
class MatchEvent:
    fixture_id: int
    event_id: str
    minute: int | None
    event_type: str
    team_id: int | None
    player_name: str | None = None