from datetime import datetime

from app.football.models import Fixture, Team
from app.football.provider import FootballProvider


class FootballService:

    def __init__(self, provider: FootballProvider):
        self.provider = provider

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