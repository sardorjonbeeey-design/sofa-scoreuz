"""Freshness-aware cache for time-sensitive provider data.

``MemoryCache`` answers "is there a value?". Live scores, today's
fixtures and standings also need "how old is it, and may I still show it
if the provider is failing?". This cache therefore returns a
``Snapshot`` that carries the fetch time and a ``stale`` flag, so the
interface can say "updated 21:05" or "could not refresh, showing 20:40"
instead of presenting old data as current.

Behaviour:

* A fresh entry (younger than ``ttl``) is returned without any upstream
  request, for every user.
* Concurrent requests for the same key share ONE upstream request.
* If the upstream request fails with a provider error, an entry younger
  than ``max_stale`` is returned marked ``stale``; with ``max_stale=0``
  (live scores) old data is never served, the error is raised.
* After a failure the key is "cooling down": further requests fail (or
  fall back to stale data) immediately instead of hitting a provider
  that just said "quota exhausted" or "rate limited".
* Errors are never cached as data.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.football.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Seconds a key stays in "cooling down" after each kind of failure.
DEFAULT_ERROR_BACKOFF: tuple[tuple[type[ProviderError], float], ...] = (
    (ProviderAuthError, 300.0),
    (ProviderQuotaError, 60.0),
    (ProviderRequestError, 30.0),
    (ProviderUnavailableError, 5.0),
)


@dataclass(frozen=True)
class Snapshot(Generic[T]):
    value: T
    fetched_at: float  # unix time of the successful upstream fetch
    stale: bool = False


@dataclass
class _Entry:
    value: object
    fetched: float  # monotonic
    fetched_wall: float
    keep_until: float  # monotonic; after this the entry is dropped


@dataclass
class _Failure:
    until: float
    error: ProviderError


class SnapshotCache:

    def __init__(
        self,
        max_items: int = 500,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        error_backoff: tuple[tuple[type[ProviderError], float], ...]
        | None = None,
    ):
        if max_items < 1:
            raise ValueError("max_items must be at least 1.")

        self._entries: dict[str, _Entry] = {}
        self._failures: dict[str, _Failure] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._max_items = max_items
        self._clock = clock
        self._wall = wall_clock
        self._backoff = (
            DEFAULT_ERROR_BACKOFF if error_backoff is None else error_backoff
        )

    def __len__(self) -> int:
        return len(self._entries)

    async def get(
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
        *,
        ttl: float,
        max_stale: float = 0.0,
    ) -> Snapshot[T]:
        now = self._clock()
        entry = self._entries.get(key)

        if entry is not None and now - entry.fetched < ttl:
            return Snapshot(entry.value, entry.fetched_wall)

        failure = self._failures.get(key)

        if failure is not None:
            if now < failure.until:
                return self._stale_or_raise(
                    key,
                    type(failure.error)(*failure.error.args),
                    max_stale,
                )

            self._failures.pop(key, None)

        task = self._inflight.get(key)

        if task is None:
            task = asyncio.ensure_future(
                self._load(key, loader, ttl, max_stale)
            )
            self._inflight[key] = task
            task.add_done_callback(
                lambda finished, k=key: self._finished(k, finished)
            )

        try:
            # shield(): a cancelled waiter must not cancel the shared
            # upstream request.
            return await asyncio.shield(task)
        except ProviderError as exc:
            return self._stale_or_raise(key, exc, max_stale)

    async def _load(self, key, loader, ttl, max_stale) -> Snapshot:
        try:
            value = await loader()
        except ProviderError as exc:
            self._remember_failure(key, exc)
            raise

        now = self._clock()
        entry = _Entry(
            value=value,
            fetched=now,
            fetched_wall=self._wall(),
            keep_until=now + max(ttl, max_stale),
        )

        self._store(key, entry)
        self._failures.pop(key, None)

        return Snapshot(value, entry.fetched_wall)

    def _finished(self, key: str, finished: asyncio.Future) -> None:
        if self._inflight.get(key) is finished:
            self._inflight.pop(key, None)

        # Mark the exception as retrieved: no "never retrieved" noise
        # when every waiter was cancelled.
        if not finished.cancelled():
            finished.exception()

    def _remember_failure(self, key: str, error: ProviderError) -> None:
        for error_type, seconds in self._backoff:
            if isinstance(error, error_type):
                if seconds > 0:
                    self._failures[key] = _Failure(
                        until=self._clock() + seconds,
                        error=error,
                    )
                return

    def _stale_or_raise(
        self,
        key: str,
        error: ProviderError,
        max_stale: float,
    ) -> Snapshot:
        entry = self._entries.get(key)

        if entry is not None and (
            self._clock() - entry.fetched <= max_stale
        ):
            logger.warning(
                "Serving stale data for %s after %s.",
                key,
                type(error).__name__,
            )
            return Snapshot(entry.value, entry.fetched_wall, stale=True)

        raise error

    def _store(self, key: str, entry: _Entry) -> None:
        if key not in self._entries and (
            len(self._entries) >= self._max_items
        ):
            self._make_room()

        self._entries[key] = entry

    def _make_room(self) -> None:
        now = self._clock()

        for key in [
            k for k, e in self._entries.items() if now >= e.keep_until
        ]:
            self._entries.pop(key, None)

        while len(self._entries) >= self._max_items:
            oldest = min(
                self._entries,
                key=lambda k: self._entries[k].fetched,
            )
            self._entries.pop(oldest, None)
