"""Freshness, sharing, back-off and stale-if-error of SnapshotCache."""

import asyncio

import pytest

from app.cache.snapshot import SnapshotCache
from app.football.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderUnavailableError,
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Loader:
    """Counts calls; returns scripted values or raises scripted errors."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "value"

        if isinstance(outcome, Exception):
            raise outcome

        return outcome


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cache(clock):
    return SnapshotCache(clock=clock, wall_clock=clock)


async def test_fresh_data_is_served_without_a_second_request(cache, clock):
    loader = Loader("A")

    first = await cache.get("k", loader, ttl=60)
    clock.advance(59)
    second = await cache.get("k", loader, ttl=60)

    assert (first.value, second.value) == ("A", "A")
    assert loader.calls == 1
    assert second.stale is False
    assert second.fetched_at == first.fetched_at


async def test_data_is_refetched_once_it_expires(cache, clock):
    loader = Loader("A", "B")

    await cache.get("k", loader, ttl=60)
    clock.advance(60)
    refreshed = await cache.get("k", loader, ttl=60)

    assert refreshed.value == "B"
    assert loader.calls == 2


async def test_different_keys_are_independent(cache):
    a, b = Loader("A"), Loader("B")

    assert (await cache.get("a", a, ttl=60)).value == "A"
    assert (await cache.get("b", b, ttl=60)).value == "B"


async def test_concurrent_requests_share_one_upstream_call(cache):
    gate = asyncio.Event()
    calls = 0

    async def slow():
        nonlocal calls
        calls += 1
        await gate.wait()
        return "shared"

    tasks = [
        asyncio.create_task(cache.get("k", slow, ttl=60)) for _ in range(20)
    ]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert {r.value for r in results} == {"shared"}


async def test_a_cancelled_waiter_does_not_break_the_others(cache):
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return "ok"

    first = asyncio.create_task(cache.get("k", slow, ttl=60))
    second = asyncio.create_task(cache.get("k", slow, ttl=60))
    await asyncio.sleep(0)
    first.cancel()
    gate.set()

    assert (await second).value == "ok"


async def test_errors_are_never_cached_as_data(clock):
    cache = SnapshotCache(clock=clock, wall_clock=clock, error_backoff=())
    loader = Loader(ProviderUnavailableError("down"), "recovered")

    with pytest.raises(ProviderUnavailableError):
        await cache.get("k", loader, ttl=60)

    assert (await cache.get("k", loader, ttl=60)).value == "recovered"


async def test_stale_data_is_served_when_the_provider_fails(cache, clock):
    loader = Loader("old", ProviderUnavailableError("down"))

    await cache.get("k", loader, ttl=60, max_stale=3600)
    clock.advance(120)
    snapshot = await cache.get("k", loader, ttl=60, max_stale=3600)

    assert snapshot.value == "old"
    assert snapshot.stale is True


async def test_data_older_than_max_stale_is_not_served(cache, clock):
    loader = Loader("old", ProviderUnavailableError("down"))

    await cache.get("k", loader, ttl=60, max_stale=600)
    clock.advance(601)

    with pytest.raises(ProviderUnavailableError):
        await cache.get("k", loader, ttl=60, max_stale=600)


async def test_live_style_data_is_never_served_stale(cache, clock):
    loader = Loader("score 1-0", ProviderQuotaError("out of quota"))

    await cache.get("live", loader, ttl=60, max_stale=0)
    clock.advance(61)

    with pytest.raises(ProviderQuotaError):
        await cache.get("live", loader, ttl=60, max_stale=0)


async def test_quota_error_cools_down_instead_of_hammering(cache, clock):
    loader = Loader(ProviderQuotaError("limit"), "value")

    with pytest.raises(ProviderQuotaError):
        await cache.get("k", loader, ttl=60)

    clock.advance(30)

    with pytest.raises(ProviderQuotaError):
        await cache.get("k", loader, ttl=60)

    assert loader.calls == 1  # the second request never reached the API

    clock.advance(31)

    assert (await cache.get("k", loader, ttl=60)).value == "value"
    assert loader.calls == 2


async def test_cooldown_still_serves_stale_data(cache, clock):
    loader = Loader("old", ProviderQuotaError("limit"))

    await cache.get("k", loader, ttl=10, max_stale=3600)
    clock.advance(20)
    await cache.get("k", loader, ttl=10, max_stale=3600)  # fails, stale
    clock.advance(5)
    snapshot = await cache.get("k", loader, ttl=10, max_stale=3600)

    assert snapshot.stale is True
    assert loader.calls == 2


async def test_auth_errors_cool_down_longer_than_quota_errors(cache, clock):
    loader = Loader(ProviderAuthError("bad key"), "value")

    with pytest.raises(ProviderAuthError):
        await cache.get("k", loader, ttl=60)

    clock.advance(120)

    with pytest.raises(ProviderAuthError):
        await cache.get("k", loader, ttl=60)

    assert loader.calls == 1


async def test_unexpected_exceptions_propagate_and_are_not_remembered(
    cache,
):
    loader = Loader(RuntimeError("bug"), "fine")

    with pytest.raises(RuntimeError):
        await cache.get("k", loader, ttl=60)

    assert (await cache.get("k", loader, ttl=60)).value == "fine"


async def test_cache_size_is_bounded(clock):
    cache = SnapshotCache(max_items=3, clock=clock, wall_clock=clock)

    for index in range(10):
        clock.advance(1)
        await cache.get(f"k{index}", Loader(index), ttl=1000)

    assert len(cache) <= 3


def test_max_items_must_be_positive():
    with pytest.raises(ValueError):
        SnapshotCache(max_items=0)
