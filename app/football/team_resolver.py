from difflib import SequenceMatcher

from app.football.models import Team
from app.football.provider import FootballProvider


ALIASES = {
    "bayern": ["Bayern Munich"],
    "bavaria": ["Bayern Munich"],
    "bayer munich": ["Bayern Munich"],
    "fc bayern": ["Bayern Munich"],
    "bayern munich": ["Bayern Munich"],
    "bayern munchen": ["Bayern Munich"],
    "бавария": ["Bayern Munich"],
    "бавария мюнхен": ["Bayern Munich"],
    "барселона": ["Barcelona"],
    "barselona": ["Barcelona"],
    "barca": ["Barcelona"],
    "barça": ["Barcelona"],
    "man u": ["Manchester United"],
    "man united": ["Manchester United"],
    "man utd": ["Manchester United"],
    "ман юнайтед": ["Manchester United"],
    "манчестер юнайтед": ["Manchester United"],
    "psg": ["Paris Saint-Germain"],
    "psj": ["Paris Saint-Germain"],
    "псж": ["Paris Saint-Germain"],
}


def normalize(value: str) -> str:
    return " ".join(
        value.lower()
        .replace("-", " ")
        .replace("_", " ")
        .split()
    )


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None,
        normalize(left),
        normalize(right),
    ).ratio()


class TeamResolver:

    def __init__(self, provider: FootballProvider):
        self.provider = provider

    async def resolve(self, query: str) -> list[Team]:
        normalized_query = normalize(query)

        search_queries = [query]

        for alias, targets in ALIASES.items():
            if normalized_query == alias:
                search_queries.extend(targets)

        if normalized_query.startswith("man "):
            search_queries.append("Manchester United")

        if normalized_query.startswith("bar"):
            search_queries.append("Barcelona")

        if normalized_query.startswith("bayer"):
            search_queries.extend(
                [
                    "Bayern Munich",
                    "Bayer Leverkusen",
                ]
            )

        if normalized_query.startswith("ps"):
            search_queries.append("Paris Saint-Germain")

        found: dict[int, Team] = {}

        for search_query in search_queries:
            try:
                teams = await self.provider.search_teams(
                    search_query
                )
            except Exception:
                continue

            for team in teams:
                found[team.id] = team

        teams = list(found.values())

        if not teams:
            return []

        scored = []

        for team in teams:
            name_score = similarity(
                query,
                team.name,
            )

            normalized_name = normalize(team.name)

            if normalized_query == normalized_name:
                score = 1.0
            elif normalized_query in normalized_name:
                score = max(name_score, 0.90)
            else:
                score = name_score

            for alias, targets in ALIASES.items():
                if (
                    normalized_query == alias
                    and team.name in targets
                ):
                    score = 1.0

            scored.append(
                (
                    score,
                    team,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            team
            for score, team in scored
            if score >= 0.45
        ][:10]