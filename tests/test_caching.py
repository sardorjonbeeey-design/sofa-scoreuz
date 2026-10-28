import asyncio

import pytest

from app.cache.cache import MemoryCache
from app.football.caching import (
    CachingFootballProvider,
    search_cache_key,
)
from app.football.errors import ProviderQuotaError
from app.football.team_directory import TeamDirectory
from tests.conftest import make_team
from tests.fakes import StubProvider


class CountingProvider(StubProvider):
    def __init__(self, teams=None, error=None, delay=0.0):
        self.teams = teams or []
        self.error = error
        self.delay = delay
        self.search_calls = 0
        self.fixture_calls = 0
        self.event_calls = 0

    async def search_teams(self, query):
        self.search_calls += 1

        if self.delay:
            await asyncio.sleep(self.delay)

        if self.error:
            raise self.error

        return list(self.teams)

    async def get_team_fixtures(self, team_id, from_date, to_date):
        self.fixture_calls += 1
        return []

    async def get_live_events(self, fixture_id):
        self.event_calls += 1
        return []


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


BARCA = make_team(529, "Barcelona", country="Spain")


async def test_repeated_searches_hit_the_cache():
    inner = CountingProvider([BARCA])
    provider = CachingFootballProvider(inner)

    first = await provider.search_teams("Barcelona")
    second = await provider.search_teams("  barcelona ")

    assert first == second == [BARCA]
    assert inner.search_calls == 1


async def test_cache_key_is_normalised():
    assert search_cache_key("  Bar  CELONA ") == search_cache_key(
        "bar celona"
    )


async def test_entries_expire():
    clock = FakeClock()
    inner = CountingProvider([BARCA])
    provider = CachingFootballProvider(
        inner,
        MemoryCache(clock=clock),
        search_ttl=100,
    )

    await provider.search_teams("barcelona")
    clock.now += 99
    await provider.search_teams("barcelona")
    assert inner.search_calls == 1

    clock.now += 2
    await provider.search_teams("barcelona")
    assert inner.search_calls == 2


async def test_empty_results_use_a_shorter_lifetime():
    clock = FakeClock()
    inner = CountingProvider([])
    provider = CachingFootballProvider(
        inner,
        MemoryCache(clock=clock),
        search_ttl=1000,
        empty_ttl=10,
    )

    await provider.search_teams("typo")
    clock.now += 5
    await provider.search_teams("typo")
    assert inner.search_calls == 1

    clock.now += 10
    await provider.search_teams("typo")
    assert inner.search_calls == 2


async def test_errors_are_never_cached():
    inner = CountingProvider(error=ProviderQuotaError("limit"))
    provider = CachingFootballProvider(inner)

    for _ in range(3):
        with pytest.raises(ProviderQuotaError):
            await provider.search_teams("barcelona")

    assert inner.search_calls == 3

    # Once the provider recovers, results flow and are cached.
    inner.error = None
    inner.teams = [BARCA]
    assert await provider.search_teams("barcelona") == [BARCA]


async def test_concurrent_identical_searches_share_one_request():
    inner = CountingProvider([BARCA], delay=0.05)
    provider = CachingFootballProvider(inner)

    results = await asyncio.gather(
        *(provider.search_teams("barcelona") for _ in range(10))
    )

    assert inner.search_calls == 1
    assert all(r == [BARCA] for r in results)


async def test_concurrent_searches_all_see_the_same_failure():
    inner = CountingProvider(error=ProviderQuotaError("limit"), delay=0.02)
    provider = CachingFootballProvider(inner)

    outcomes = await asyncio.gather(
        *(provider.search_teams("barcelona") for _ in range(5)),
        return_exceptions=True,
    )

    assert inner.search_calls == 1
    assert all(isinstance(o, ProviderQuotaError) for o in outcomes)


async def test_cancelled_waiter_does_not_break_the_others():
    inner = CountingProvider([BARCA], delay=0.05)
    provider = CachingFootballProvider(inner)

    doomed = asyncio.ensure_future(provider.search_teams("barcelona"))
    survivor = asyncio.ensure_future(provider.search_teams("barcelona"))
    await asyncio.sleep(0.01)
    doomed.cancel()

    assert await survivor == [BARCA]
    assert inner.search_calls == 1


async def test_fixtures_and_live_events_are_never_cached():
    inner = CountingProvider()
    provider = CachingFootballProvider(inner)

    for _ in range(3):
        await provider.get_team_fixtures(1, None, None)
        await provider.get_live_events(99)

    assert inner.fixture_calls == 3
    assert inner.event_calls == 3


async def test_memory_cache_is_bounded():
    cache = MemoryCache(max_items=3)

    for index in range(10):
        await cache.set(f"k{index}", index, ttl_seconds=100 + index)

    assert len(cache) == 3
    # Entries closest to expiry were evicted; the newest survive.
    assert await cache.get("k9") == 9
    assert await cache.get("k0") is None


async def test_memory_cache_purges_expired_before_evicting_live_entries():
    clock = FakeClock()
    cache = MemoryCache(max_items=2, clock=clock)

    await cache.set("old", 1, ttl_seconds=5)
    await cache.set("live", 2, ttl_seconds=500)
    clock.now += 10
    await cache.set("new", 3, ttl_seconds=500)

    assert await cache.get("live") == 2
    assert await cache.get("new") == 3


async def test_team_directory_remembers_and_expires():
    clock = FakeClock()
    directory = TeamDirectory(MemoryCache(clock=clock), ttl_seconds=60)

    await directory.remember([BARCA])
    assert await directory.get(529) == BARCA
    assert await directory.get(1) is None

    clock.now += 61
    assert await directory.get(529) is None
