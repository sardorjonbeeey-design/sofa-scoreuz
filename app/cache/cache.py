from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class MemoryCache:

    def __init__(self):
        self._items: dict[str, CacheEntry] = {}

    async def get(self, key: str):
        item = self._items.get(key)

        if not item:
            return None

        if datetime.utcnow() >= item.expires_at:
            self._items.pop(key, None)
            return None

        return item.value

    async def set(
        self,
        key: str,
        value,
        ttl_seconds: int,
    ) -> None:

        self._items[key] = CacheEntry(
            value=value,
            expires_at=datetime.utcnow()
            + timedelta(seconds=ttl_seconds),
        )

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)