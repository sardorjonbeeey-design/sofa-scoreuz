import random
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


# Countries with strong relevance for Flash Football.
PRIORITY_COUNTRIES = {
    "Uzbekistan": 100,
    "England": 95,
    "Spain": 95,
    "Italy": 95,
    "Germany": 95,
    "France": 95,
    "Russia": 90,
    "Turkey": 90,
    "Türkiye": 90,
    "Saudi-Arabia": 85,
    "Saudi Arabia": 85,
    "USA": 85,
    "United States": 85,
}


COUNTRY_CODES = {
    "Uzbekistan": "UZB",
    "England": "ENG",
    "Spain": "ESP",
    "Italy": "ITA",
    "Germany": "GER",
    "France": "FRA",
    "Russia": "RUS",
    "Turkey": "TUR",
    "Türkiye": "TUR",
    "Saudi-Arabia": "KSA",
    "Saudi Arabia": "KSA",
    "USA": "USA",
    "United States": "USA",
}


FLAG_EMOJIS = {
    "Uzbekistan": "🇺🇿",
    "England": "🏴",
    "Spain": "🇪🇸",
    "Italy": "🇮🇹",
    "Germany": "🇩🇪",
    "France": "🇫🇷",
    "Russia": "🇷🇺",
    "Turkey": "🇹🇷",
    "Türkiye": "🇹🇷",
    "Saudi-Arabia": "🇸🇦",
    "Saudi Arabia": "🇸🇦",
    "USA": "🇺🇸",
    "United States": "🇺🇸",
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


def country_priority(team: Team) -> int:
    return PRIORITY_COUNTRIES.get(
        team.country or "",
        10,
    )


def disambiguator(team: Team) -> str:
    options = []

    if team.country:
        flag = FLAG_EMOJIS.get(team.country)

        if flag:
            options.append(flag)

        code = COUNTRY_CODES.get(team.country)

        if code:
            options.append(f"({code})")

        options.append(f"· {team.country}")

    if team.code:
        options.append(f"· {team.code}")

    if not options:
        return ""

    return random.choice(options)


def display_name(team: Team) -> str:
    suffix = disambiguator(team)

    if suffix:
        return f"{team.name} {suffix}"

    return team.name


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
            normalized_name = normalize(team.name)
            name_score = similarity(
                query,
                team.name,
            )

            if normalized_query == normalized_name:
                match_score = 1000
            elif normalized_query in normalized_name:
                match_score = 800 + (name_score * 100)
            else:
                match_score = name_score * 100

            # Explicit aliases get the strongest possible ranking.
            for alias, targets in ALIASES.items():
                if (
                    normalized_query == alias
                    and team.name in targets
                ):
                    match_score = 1200

            # National teams are highly relevant.
            national_bonus = 150 if team.national else 0

            # Strong country preference.
            country_bonus = country_priority(team)

            # Exact famous-club shortcuts.
            famous_bonus = 0

            famous_names = {
                "Barcelona",
                "Real Madrid",
                "Bayern Munich",
                "Bayer Leverkusen",
                "Manchester United",
                "Manchester City",
                "Liverpool",
                "Arsenal",
                "Chelsea",
                "Paris Saint-Germain",
                "Juventus",
                "Inter",
                "AC Milan",
                "Borussia Dortmund",
                "Galatasaray",
                "Fenerbahce",
                "Besiktas",
                "Al Hilal",
                "Al Nassr",
                "Inter Miami CF",
            }

            if team.name in famous_names:
                famous_bonus = 75

            total_score = (
                match_score
                + national_bonus
                + country_bonus
                + famous_bonus
            )

            scored.append(
                (
                    total_score,
                    team,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        # Keep the search compact. We don't want a wall of
        # obscure clubs even when the API returns many matches.
        return [
            team
            for _, team in scored[:8]
        ]


def format_team_result(team: Team) -> str:
    return display_name(team)