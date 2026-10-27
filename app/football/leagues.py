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
    FeaturedLeague(203, "Süper Lig", "🇹🇷"),
    FeaturedLeague(235, "Russian Premier League", "🇷🇺"),
    FeaturedLeague(307, "Saudi Pro League", "🇸🇦"),
)

FEATURED_COUNTRIES: tuple[FeaturedCountry, ...] = (
    FeaturedCountry("UZ", "Uzbekistan", "🇺🇿"),
)

_PRIORITY = {league.id: index for index, league in enumerate(FEATURED_LEAGUES)}


# Additional competitions are included in live/today feeds, but only actual
# leagues above are offered in the standings menu.
FEATURED_CUP_AND_INTERNATIONAL_IDS = frozenset({
    1,    # FIFA World Cup
    4,    # UEFA European Championship
    5,    # UEFA Nations League
    6,    # Africa Cup of Nations
    7,    # AFC Asian Cup
    9,    # Copa América
    13,   # Olympic football tournament
    15,   # FIFA Club World Cup
    29,   # World Cup qualification: Africa
    30,   # World Cup qualification: Asia
    31,   # World Cup qualification: CONCACAF
    32,   # World Cup qualification: Europe
    33,   # World Cup qualification: Oceania
    34,   # World Cup qualification: South America
    45,   # FA Cup
    48,   # English League Cup
    66,   # Coupe de France
    81,   # DFB-Pokal
    137,  # Coppa Italia
    143,  # Copa del Rey
    206,  # Turkish Cup
    237,  # Russian Cup
    504,  # Saudi King's Cup
})


def featured_league_ids() -> frozenset[int]:
    return frozenset(_PRIORITY)


def featured_competition_ids() -> frozenset[int]:
    return frozenset(_PRIORITY) | FEATURED_CUP_AND_INTERNATIONAL_IDS


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
