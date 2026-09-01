from abc import ABC, abstractmethod
from datetime import datetime

from app.football.models import Fixture, MatchEvent, Team


class FootballProvider(ABC):

    @abstractmethod
    async def search_teams(self, query: str) -> list[Team]:
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
    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:
        raise NotImplementedError