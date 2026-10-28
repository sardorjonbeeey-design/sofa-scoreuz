import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class MemoryCache:
    """Small in-process TTL cache.

    * Expiry uses a monotonic clock, so wall-clock changes cannot
      extend or shorten lifetimes.
    * The cache is bounded: when ``max_items`` is reached, expired
      entries are purged first and then the entries closest to expiry
      are evicted.
    * It is intentionally separate from user data (favorites,
      language), which lives in the persistence layer.
    """

    def __init__(
        self,
        max_items: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_items < 1:
            raise ValueError("max_items must be at least 1.")

        self._items: dict[str, CacheEntry] = {}
        self._max_items = max_items
        self._clock = clock

    def __len__(self) -> int:
        return len(self._items)

    async def get(self, key: str):
        item = self._items.get(key)

        if not item:
            return None

        if self._clock() >= item.expires_at:
            self._items.pop(key, None)
            return None

        return item.value

    async def set(
        self,
        key: str,
        value,
        ttl_seconds: int,
    ) -> None:

        if ttl_seconds <= 0:
            self._items.pop(key, None)
            return

        if key not in self._items and len(self._items) >= self._max_items:
            self._make_room()

        self._items[key] = CacheEntry(
            value=value,
            expires_at=self._clock() + ttl_seconds,
        )

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)

    async def clear(self) -> None:
        self._items.clear()

    def _make_room(self) -> None:
        now = self._clock()

        expired = [
            key
            for key, item in self._items.items()
            if now >= item.expires_at
        ]

        for key in expired:
            self._items.pop(key, None)

        while len(self._items) >= self._max_items:
            oldest = min(
                self._items,
                key=lambda k: self._items[k].expires_at,
            )
            self._items.pop(oldest, None)
