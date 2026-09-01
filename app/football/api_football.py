from datetime import datetime

import httpx

from app.football.models import Fixture, MatchEvent, Team
from app.football.provider import FootballProvider


class ApiFootballProvider(FootballProvider):
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"x-apisports-key": api_key},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def search_teams(self, query: str) -> list[Team]:
        response = await self.client.get(
            "/teams",
            params={"search": query},
        )
        response.raise_for_status()

        data = response.json()

        return [
            Team(
                id=item["team"]["id"],
                name=item["team"]["name"],
                logo_url=item["team"].get("logo"),
            )
            for item in data.get("response", [])
        ]

    async def get_team_fixtures(
        self,
        team_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Fixture]:

        response = await self.client.get(
            "/fixtures",
            params={
                "team": team_id,
                "from": from_date.date().isoformat(),
                "to": to_date.date().isoformat(),
            },
        )

        response.raise_for_status()

        data = response.json()
        fixtures = []

        for item in data.get("response", []):
            fixture = item["fixture"]
            teams = item["teams"]

            fixtures.append(
                Fixture(
                    id=fixture["id"],
                    home_team=Team(
                        id=teams["home"]["id"],
                        name=teams["home"]["name"],
                        logo_url=teams["home"].get("logo"),
                    ),
                    away_team=Team(
                        id=teams["away"]["id"],
                        name=teams["away"]["name"],
                        logo_url=teams["away"].get("logo"),
                    ),
                    start_time=datetime.fromisoformat(
                        fixture["date"].replace("Z", "+00:00")
                    ),
                    competition=item["league"]["name"],
                    venue=(fixture.get("venue") or {}).get("name"),
                )
            )

        return fixtures

    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:

        response = await self.client.get(
            "/fixtures",
            params={"id": fixture_id},
        )

        response.raise_for_status()

        data = response.json()
        events = []

        for item in data.get("response", []):
            for index, event in enumerate(item.get("events", [])):

                events.append(
                    MatchEvent(
                        fixture_id=fixture_id,
                        event_id=str(
                            event.get("id")
                            or f"{fixture_id}:{index}"
                        ),
                        minute=(event.get("time") or {}).get("elapsed"),
                        event_type=event.get("type", "unknown"),
                        team_id=(event.get("team") or {}).get("id"),
                        player_name=(event.get("player") or {}).get("name"),
                    )
                )

        return events