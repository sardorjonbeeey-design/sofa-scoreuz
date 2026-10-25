import pytest

from app.football.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.football.provider import FootballProvider
from app.football.team_resolver import (
    ResolveStatus,
    TeamResolver,
    display_name,
)
from tests.conftest import make_team


class FakeProvider(FootballProvider):
    """Scripted provider: maps query -> teams or an exception."""

    def __init__(self, script):
        self.script = {k.lower(): v for k, v in script.items()}
        self.queries: list[str] = []

    async def search_teams(self, query):
        self.queries.append(query)
        outcome = self.script.get(query.lower(), [])

        if isinstance(outcome, Exception):
            raise outcome

        return list(outcome)

    async def get_team_fixtures(self, team_id, from_date, to_date):
        raise AssertionError("not used")

    async def get_live_events(self, fixture_id):
        raise AssertionError("not used")


BARCA = make_team(529, "Barcelona", country="Spain", code="BAR")
BARCA_SC = make_team(1, "Barcelona SC", country="Ecuador")
BAYERN = make_team(157, "Bayern Munich", country="Germany")
LEVERKUSEN = make_team(168, "Bayer Leverkusen", country="Germany")


async def test_genuine_no_match():
    resolver = TeamResolver(FakeProvider({"nothing": []}))

    result = await resolver.resolve("nothing")

    assert result.status is ResolveStatus.NO_MATCH
    assert result.teams == []


async def test_single_candidate_is_matched():
    resolver = TeamResolver(FakeProvider({"liverpool": [
        make_team(40, "Liverpool", country="England")]}))

    result = await resolver.resolve("liverpool")

    assert result.status is ResolveStatus.MATCHED
    assert [t.id for t in result.teams] == [40]


async def test_multiple_candidates_are_ambiguous_and_ranked():
    resolver = TeamResolver(FakeProvider({"barcelona": [BARCA_SC, BARCA]}))

    result = await resolver.resolve("barcelona")

    assert result.status is ResolveStatus.AMBIGUOUS
    assert [t.name for t in result.teams] == ["Barcelona", "Barcelona SC"]


async def test_ordering_is_stable_across_runs():
    teams = [make_team(i, "Same Name FC", country="Spain")
             for i in (5, 3, 9, 1)]

    orders = set()

    for _ in range(25):
        resolver = TeamResolver(FakeProvider({"same name": list(teams)}))
        result = await resolver.resolve("same name")
        orders.add(tuple(t.id for t in result.teams))

    assert orders == {(1, 3, 5, 9)}


async def test_results_are_limited_to_eight():
    many = [make_team(i, f"Team {i}", country="Spain") for i in range(20)]
    resolver = TeamResolver(FakeProvider({"team": many}))

    result = await resolver.resolve("team")

    assert len(result.teams) == 8


@pytest.mark.parametrize(
    "error, status",
    [
        (ProviderQuotaError("limit"), ResolveStatus.QUOTA_EXCEEDED),
        (ProviderAuthError("bad key"), ResolveStatus.AUTH_ERROR),
        (ProviderUnavailableError("down"), ResolveStatus.UNAVAILABLE),
    ],
)
async def test_provider_failures_are_not_reported_as_no_match(
    error, status
):
    resolver = TeamResolver(FakeProvider({"barcelona": error}))

    result = await resolver.resolve("barcelona")

    assert result.status is status
    assert result.status is not ResolveStatus.NO_MATCH
    assert result.teams == []


async def test_quota_failure_stops_further_requests():
    provider = FakeProvider({
        "bayern": ProviderQuotaError("limit"),
    })
    resolver = TeamResolver(provider)

    # "bayern" fans out to several searches; after a quota failure
    # no further upstream requests may be spent.
    result = await resolver.resolve("bayern")

    assert result.status is ResolveStatus.QUOTA_EXCEEDED
    assert provider.queries == ["bayern"]


async def test_auth_failure_stops_further_requests():
    provider = FakeProvider({"bayern": ProviderAuthError("bad")})

    result = await TeamResolver(provider).resolve("bayern")

    assert result.status is ResolveStatus.AUTH_ERROR
    assert len(provider.queries) == 1


async def test_most_severe_error_is_reported():
    provider = FakeProvider({
        "bayern": ProviderUnavailableError("down"),
        "bayern munich": ProviderUnavailableError("down"),
        "bayer leverkusen": ProviderUnavailableError("down"),
    })

    result = await TeamResolver(provider).resolve("bayern")

    assert result.status is ResolveStatus.UNAVAILABLE


async def test_partial_failure_still_returns_the_teams_that_were_found():
    provider = FakeProvider({
        "bayern": ProviderUnavailableError("blip"),
        "bayern munich": [BAYERN],
        "bayer leverkusen": [LEVERKUSEN],
    })

    result = await TeamResolver(provider).resolve("bayern")

    assert result.has_teams
    assert {t.id for t in result.teams} == {157, 168}


async def test_cyrillic_alias_still_works_when_raw_query_is_rejected():
    provider = FakeProvider({
        "бавария": ProviderRequestError("search must be alphanumeric"),
        "bayern munich": [BAYERN],
    })

    result = await TeamResolver(provider).resolve("Бавария")

    assert [t.name for t in result.teams] == ["Bayern Munich"]
    assert result.teams[0].id == 157


async def test_unsearchable_query_is_no_match_not_an_outage():
    provider = FakeProvider({
        "??": ProviderRequestError("search must be alphanumeric"),
    })

    result = await TeamResolver(provider).resolve("??")

    assert result.status is ResolveStatus.NO_MATCH


async def test_alias_ranks_target_first():
    provider = FakeProvider({
        "psg": [make_team(9, "PSG Pari Nijni", country="Russia"),
                make_team(85, "Paris Saint-Germain", country="France")],
        "paris saint-germain": [
            make_team(85, "Paris Saint-Germain", country="France")],
    })

    result = await TeamResolver(provider).resolve("PSG")

    assert result.teams[0].name == "Paris Saint-Germain"


async def test_duplicate_upstream_searches_are_not_sent():
    provider = FakeProvider({"barcelona": [BARCA]})

    # "barcelona" matches the alias list AND the "bar..." shortcut,
    # but must still be searched only once.
    await TeamResolver(provider).resolve("Barcelona")

    assert provider.queries == ["Barcelona"]


async def test_priority_countries_outrank_obscure_ones():
    provider = FakeProvider({"united fc": [
        make_team(1, "United FC", country="Gabon"),
        make_team(2, "United FC", country="England"),
    ]})

    result = await TeamResolver(provider).resolve("united fc")

    assert [t.id for t in result.teams] == [2, 1]


def test_display_names_are_stable_and_distinguish_same_names():
    spain = make_team(1, "Barcelona", country="Spain")
    other = make_team(2, "Barcelona", country="Ecuador")

    for _ in range(100):
        assert display_name(spain) == "Barcelona 🇪🇸 Spain"
        assert display_name(other) == "Barcelona Ecuador"

    assert display_name(make_team(3, "Team X")) == "Team X"
    assert display_name(make_team(4, "Team Y", code="TMY")) == "Team Y TMY"
