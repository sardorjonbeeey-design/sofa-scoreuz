"""FootballService: shared caching, dates, standings, team pages."""

from datetime import date, datetime, timedelta

import pytest

from app.cache.snapshot import SnapshotCache
from app.football.errors import ProviderQuotaError, ProviderUnavailableError
from app.football.models import League
from app.football.service import CacheTimes, FootballService, split_team_matches
from tests.fakes import UTC, FakeFootball, make_fixture, make_table


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


def make_service(provider=None, *, clock=None, **kwargs):
    provider = provider or FakeFootball()
    clock = clock or Clock()
    service = FootballService(
        provider,
        cache=SnapshotCache(clock=clock, wall_clock=clock),
        **kwargs,
    )
    return service, provider, clock


async def test_live_scores_are_fetched_once_for_many_users():
    service, provider, _ = make_service()
    provider.live = [make_fixture(1, status="1H", elapsed=12)]

    results = [await service.live_fixtures() for _ in range(50)]

    assert provider.calls["live"] == 1
    assert all(len(r.value) == 1 for r in results)


async def test_live_scores_are_refreshed_after_their_ttl():
    service, provider, clock = make_service(times=CacheTimes(live=60))

    await service.live_fixtures()
    clock.now += 61
    await service.live_fixtures()

    assert provider.calls["live"] == 2


async def test_todays_fixtures_use_the_display_timezone():
    service, provider, _ = make_service(timezone="Asia/Tashkent")
    service.now_local = lambda: datetime(
        2026, 10, 26, 3, 0, tzinfo=service.tz
    )

    await service.todays_fixtures()

    # 03:00 in Tashkent is still the previous day in UTC; the service
    # must ask for Tashkent's date, in Tashkent's timezone.
    assert provider.last_date == (date(2026, 10, 26), "Asia/Tashkent")


async def test_the_fixtures_cache_rolls_over_at_local_midnight():
    service, provider, _ = make_service()
    day = [datetime(2026, 10, 26, 23, 59, tzinfo=service.tz)]
    service.now_local = lambda: day[0]

    await service.todays_fixtures()
    await service.todays_fixtures()
    assert provider.calls["by_date"] == 1

    day[0] = day[0] + timedelta(minutes=2)  # now 27 October
    await service.todays_fixtures()

    assert provider.calls["by_date"] == 2
    assert provider.last_date[0] == date(2026, 10, 27)


async def test_standings_lookup_season_then_table_once_per_window():
    service, provider, _ = make_service()
    provider.leagues[39] = League(39, "Premier League", "England", "League", None, 2026)
    provider.tables[39] = [make_table("Arsenal", "Chelsea")]

    first = await service.league_standings(39)
    second = await service.league_standings(39)

    assert first.value.season == 2026
    assert [r.team.name for r in first.value.groups[0].rows] == [
        "Arsenal",
        "Chelsea",
    ]
    assert second.value == first.value
    assert provider.calls == {"leagues": 1, "standings": 1}


async def test_league_without_a_current_season_has_no_table_and_no_guess():
    service, provider, _ = make_service()
    provider.leagues[39] = League(39, "Premier League", None, "League", None, None)

    snapshot = await service.league_standings(39)

    assert snapshot.value.groups == ()
    assert snapshot.value.season is None
    assert "standings" not in provider.calls


async def test_unknown_league_returns_an_empty_view():
    service, _, _ = make_service()

    snapshot = await service.league_standings(39)

    assert snapshot.value.league is None
    assert snapshot.value.groups == ()


async def test_country_leagues_keep_only_domestic_leagues():
    service, provider, _ = make_service()
    provider.country_leagues = [
        League(1, "Super League", "Uzbekistan", "League", None, 2026),
        League(2, "Cup", "Uzbekistan", "Cup", None, 2026),
    ]

    snapshot = await service.country_leagues("Uzbekistan")

    assert [league.name for league in snapshot.value] == ["Super League"]


async def test_only_offered_leagues_are_known():
    service, provider, _ = make_service()
    provider.country_leagues = [
        League(777, "Super League", "Uzbekistan", "League", None, 2026),
    ]

    assert await service.is_known_league(39) is True  # featured
    assert await service.is_known_league(777) is True  # via Uzbekistan
    assert await service.is_known_league(31337) is False  # forged


async def test_known_leagues_are_rebuilt_after_a_restart():
    provider = FakeFootball()
    provider.country_leagues = [
        League(777, "Super League", "Uzbekistan", "League", None, 2026),
    ]
    old_service, _, _ = make_service(provider)
    await old_service.country_leagues("Uzbekistan")

    fresh_service, _, _ = make_service(provider)  # new process

    assert await fresh_service.is_known_league(777) is True


async def test_an_unreachable_provider_never_makes_unknown_leagues_known():
    service, provider, _ = make_service()
    provider.error = ProviderUnavailableError("down")

    assert await service.is_known_league(31337) is False


def test_team_matches_are_split_sorted_and_limited():
    base = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    fixtures = [
        make_fixture(i, status="FT", goals=(1, 0), start=base - timedelta(days=i))
        for i in range(1, 9)
    ] + [
        make_fixture(20 + i, status="NS", start=base + timedelta(days=i))
        for i in range(1, 9)
    ] + [make_fixture(99, status="CANC", start=base + timedelta(days=1))]

    matches = split_team_matches(fixtures)

    assert len(matches.recent) == 5 and len(matches.upcoming) == 5
    assert matches.recent[0].id == 1  # most recent result first
    assert matches.upcoming[0].id == 21  # soonest fixture first
    assert all(f.status != "CANC" for f in matches.upcoming)


async def test_a_team_page_costs_one_request_and_is_cached():
    service, provider, _ = make_service()
    provider.team_fixtures = [make_fixture(1, status="NS")]

    await service.team_matches(33)
    await service.team_matches(33)

    assert provider.calls["team_fixtures"] == 1


async def test_quota_errors_propagate_as_typed_errors():
    service, provider, _ = make_service()
    provider.error = ProviderQuotaError("daily limit")

    with pytest.raises(ProviderQuotaError):
        await service.live_fixtures()


async def test_todays_fixtures_fall_back_to_stale_data_but_live_does_not():
    service, provider, clock = make_service(
        times=CacheTimes(live=60, fixtures=300)
    )
    provider.live = [make_fixture(1, status="1H", elapsed=5)]
    provider.by_date = [make_fixture(2)]

    await service.live_fixtures()
    await service.todays_fixtures()

    clock.now += 400
    provider.error = ProviderUnavailableError("down")

    stale = await service.todays_fixtures()
    assert stale.stale is True and len(stale.value) == 1

    with pytest.raises(ProviderUnavailableError):
        await service.live_fixtures()


def test_unknown_timezone_falls_back_without_crashing():
    service = FootballService(FakeFootball(), timezone="Not/AZone")

    assert service.timezone_name == "Asia/Tashkent"
