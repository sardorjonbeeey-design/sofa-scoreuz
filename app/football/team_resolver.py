import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from app.football.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.football.models import Team
from app.football.provider import FootballProvider

logger = logging.getLogger(__name__)


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
    "man city": ["Manchester City"],
    "manchester city": ["Manchester City"],
    "manchester united": ["Manchester United"],
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


FAMOUS_NAMES = {
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
    """Stable label that tells same-named teams apart.

    The label depends only on the team's own data, so the same team
    is rendered identically on every search: "<flag> <country>" when
    the country is known, otherwise the team code.
    """
    parts: list[str] = []

    if team.country:
        flag = FLAG_EMOJIS.get(team.country)

        if flag:
            parts.append(flag)

        parts.append(team.country)
    elif team.code:
        parts.append(team.code)

    return " ".join(parts)


def display_name(team: Team) -> str:
    suffix = disambiguator(team)

    if suffix:
        return f"{team.name} {suffix}"

    return team.name


class ResolveStatus(str, Enum):
    MATCHED = "matched"              # exactly one candidate
    AMBIGUOUS = "ambiguous"          # several candidates, user picks
    NO_MATCH = "no_match"            # provider answered: nothing found
    QUOTA_EXCEEDED = "quota_exceeded"
    AUTH_ERROR = "auth_error"
    UNAVAILABLE = "unavailable"      # network / timeout / 5xx


@dataclass(frozen=True)
class ResolveResult:
    status: ResolveStatus
    teams: list[Team] = field(default_factory=list)

    @property
    def has_teams(self) -> bool:
        return bool(self.teams)


# Higher number = reported first when several queries failed.
_ERROR_SEVERITY = {
    ProviderAuthError: (3, ResolveStatus.AUTH_ERROR),
    ProviderQuotaError: (2, ResolveStatus.QUOTA_EXCEEDED),
    ProviderUnavailableError: (1, ResolveStatus.UNAVAILABLE),
}


def _status_for_error(error: ProviderError) -> tuple[int, ResolveStatus]:
    for error_type, outcome in _ERROR_SEVERITY.items():
        if isinstance(error, error_type):
            return outcome

    return (1, ResolveStatus.UNAVAILABLE)


class TeamResolver:

    def __init__(self, provider: FootballProvider):
        self.provider = provider

    def _search_queries(self, query: str) -> list[str]:
        normalized_query = normalize(query)

        search_queries = [query]

        for alias, targets in ALIASES.items():
            if normalized_query == alias:
                search_queries.extend(targets)

        if normalized_query.startswith("bayer"):
            search_queries.extend(
                [
                    "Bayern Munich",
                    "Bayer Leverkusen",
                ]
            )

        # Never send the same search twice: every upstream call
        # counts against the provider quota.
        unique: list[str] = []
        seen: set[str] = set()

        for item in search_queries:
            key = normalize(item)

            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    async def resolve(self, query: str) -> ResolveResult:
        """Find teams for ``query``.

        Provider failures are reported through ``ResolveResult.status``
        and are never confused with a genuine "no match".
        """
        normalized_query = normalize(query)

        found: dict[int, Team] = {}
        errors: list[ProviderError] = []

        for search_query in self._search_queries(query):
            try:
                teams = await self.provider.search_teams(search_query)
            except ProviderRequestError as exc:
                # The provider rejected this particular search string
                # (for example non-latin text). Other queries, such as
                # alias targets, may still work.
                logger.info(
                    "Provider rejected search %r: %s",
                    search_query,
                    exc,
                )
                continue
            except ProviderError as exc:
                logger.warning(
                    "Provider failure during team search (%s): %s",
                    type(exc).__name__,
                    exc,
                )
                errors.append(exc)

                # Quota and auth failures will fail again immediately:
                # stop instead of spending more requests.
                if isinstance(
                    exc,
                    (ProviderQuotaError, ProviderAuthError),
                ):
                    break

                continue

            for team in teams:
                found[team.id] = team

        teams = list(found.values())

        if not teams:
            if errors:
                _, status = max(
                    (_status_for_error(e) for e in errors),
                    key=lambda item: item[0],
                )
                return ResolveResult(status)

            # Either the provider answered with nothing, or it
            # rejected every query string as unsearchable.
            return ResolveResult(ResolveStatus.NO_MATCH)

        if errors:
            logger.warning(
                "Returning partial team results; %s upstream "
                "request(s) failed.",
                len(errors),
            )

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

            # Famous clubs should win generic one-word searches such as
            # "United" over obscure exact-name matches. Keep ordinary exact
            # searches dominant, and only apply this stronger prior when the
            # query is a genuinely ambiguous standalone token.
            ambiguous_single_terms = {"united"}
            is_ambiguous_single_term = normalized_query in ambiguous_single_terms
            famous_bonus = (
                600 if is_ambiguous_single_term and team.name in FAMOUS_NAMES
                else 75 if team.name in FAMOUS_NAMES
                else 0
            )

            if is_ambiguous_single_term and team.name not in FAMOUS_NAMES:
                match_score = min(match_score, 100)

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

        # Ties are broken by name and id so ordering never varies.
        scored.sort(
            key=lambda item: (-item[0], item[1].name, item[1].id),
        )

        # Keep the search compact. We don't want a wall of
        # obscure clubs even when the API returns many matches.
        top = [team for _, team in scored[:8]]

        status = (
            ResolveStatus.MATCHED
            if len(top) == 1
            else ResolveStatus.AMBIGUOUS
        )

        return ResolveResult(status, top)


def format_team_result(team: Team) -> str:
    return display_name(team)