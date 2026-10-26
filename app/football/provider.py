from abc import ABC, abstractmethod
from datetime import date, datetime

from app.football.models import (
    Fixture,
    League,
    MatchEvent,
    StandingsGroup,
    Team,
)


class FootballProvider(ABC):

    @abstractmethod
    async def search_teams(self, query: str) -> list[Team]:
        raise NotImplementedError

    @abstractmethod
    async def get_team(self, team_id: int) -> Team | None:
        """One team by id, or ``None`` when the provider has no such team."""
        raise NotImplementedError

    @abstractmethod
    async def get_team_fixtures(
        self,
        team_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Fixture]:
        raise NotImplementedError

    @abstractmethod
    async def get_live_fixtures(self) -> list[Fixture]:
        """Every match that is in play right now."""
        raise NotImplementedError

    @abstractmethod
    async def get_fixtures_by_date(
        self,
        day: date,
        timezone: str | None = None,
    ) -> list[Fixture]:
        """Every match scheduled on ``day`` in ``timezone`` (IANA name)."""
        raise NotImplementedError

    @abstractmethod
    async def get_leagues(
        self,
        *,
        league_id: int | None = None,
        country: str | None = None,
    ) -> list[League]:
        raise NotImplementedError

    @abstractmethod
    async def get_standings(
        self,
        league_id: int,
        season: int,
    ) -> list[StandingsGroup]:
        """League tables; an empty list means none are published."""
        raise NotImplementedError

    @abstractmethod
    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:
        raise NotImplementedError
