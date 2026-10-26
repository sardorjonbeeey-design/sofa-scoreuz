"""Competitions shown in the bot's league list.

Only league ids that are well known are listed. The NAME shown on a
standings page always comes from the provider's response, never from
this file, so a wrong id would surface as an unexpected title instead
of silently showing invented data (and a mismatch is logged).

Countries are looked up through the provider at runtime, so the local
Uzbek competitions need no hard-coded ids.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeaturedLeague:
    id: int
    name: str
    flag: str


@dataclass(frozen=True)
class FeaturedCountry:
    code: str
    name: str  # exactly as the provider spells it
    flag: str


# Order = priority in match lists and in the league menu.
FEATURED_LEAGUES: tuple[FeaturedLeague, ...] = (
    FeaturedLeague(2, "UEFA Champions League", "🇪🇺"),
    FeaturedLeague(3, "UEFA Europa League", "🇪🇺"),
    FeaturedLeague(848, "UEFA Europa Conference League", "🇪🇺"),
    FeaturedLeague(39, "Premier League", "🇬🇧"),
    FeaturedLeague(140, "La Liga", "🇪🇸"),
    FeaturedLeague(135, "Serie A", "🇮🇹"),
    FeaturedLeague(78, "Bundesliga", "🇩🇪"),
    FeaturedLeague(61, "Ligue 1", "🇫🇷"),
    FeaturedLeague(94, "Primeira Liga", "🇵🇹"),
    FeaturedLeague(88, "Eredivisie", "🇳🇱"),
    FeaturedLeague(203, "Süper Lig", "🇹🇷"),
    FeaturedLeague(235, "Russian Premier League", "🇷🇺"),
    FeaturedLeague(307, "Saudi Pro League", "🇸🇦"),
)

FEATURED_COUNTRIES: tuple[FeaturedCountry, ...] = (
    FeaturedCountry("UZ", "Uzbekistan", "🇺🇿"),
)

_PRIORITY = {league.id: index for index, league in enumerate(FEATURED_LEAGUES)}


def featured_league_ids() -> frozenset[int]:
    return frozenset(_PRIORITY)


def featured_country_names() -> frozenset[str]:
    return frozenset(country.name for country in FEATURED_COUNTRIES)


def league_priority(league_id: int | None) -> int:
    """Lower = more prominent. Unlisted leagues sort last."""
    if league_id is None:
        return len(_PRIORITY) + 1

    return _PRIORITY.get(league_id, len(_PRIORITY))


def featured_league(league_id: int) -> FeaturedLeague | None:
    for league in FEATURED_LEAGUES:
        if league.id == league_id:
            return league

    return None


def country_by_code(code: str) -> FeaturedCountry | None:
    for country in FEATURED_COUNTRIES:
        if country.code == code:
            return country

    return None
