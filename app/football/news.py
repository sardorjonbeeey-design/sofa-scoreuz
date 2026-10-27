"""Small RSS-backed football news reader.

Uses Google News RSS rather than an additional paid API key. Results are
cached briefly per query so repeated users do not trigger repeated fetches.
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

NEWS_FEED_URL = "https://news.google.com/rss/search"
NEWS_CACHE_TTL = 15 * 60
NEWS_LIMIT = 6

_GLOBAL_QUERY = (
    '("Premier League" OR "La Liga" OR "Serie A" OR Bundesliga OR '
    '"Ligue 1" OR "UEFA Champions League" OR "Europa League" OR '
    '"Süper Lig" OR "Saudi Pro League" OR Uzbekistan OR '
    '"Russian Premier League") football'
)


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str | None = None
    published: str | None = None


_cache: dict[tuple[str, str], tuple[float, tuple[NewsItem, ...]]] = {}
_lock = asyncio.Lock()


def _locale(language: str) -> tuple[str, str, str]:
    if language == "ru":
        return "ru", "RU", "RU:ru"
    return "en-US", "US", "US:en"


def parse_news_feed(payload: str, limit: int = NEWS_LIMIT) -> tuple[NewsItem, ...]:
    """Parse valid RSS items only; malformed entries are skipped."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ()

    items: list[NewsItem] = []
    for node in root.findall("./channel/item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        if not title or not url or not url.startswith(("https://", "http://")):
            continue

        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None else ""
        published = (node.findtext("pubDate") or "").strip()
        items.append(NewsItem(title, url, source or None, published or None))
        if len(items) >= limit:
            break

    return tuple(items)


async def football_news(
    *,
    team_name: str | None = None,
    language: str = "en",
    limit: int = NEWS_LIMIT,
) -> tuple[NewsItem, ...]:
    """Fetch cached global or team-specific football news."""
    query = (
        f'"{team_name}" football'
        if team_name
        else _GLOBAL_QUERY
    )
    key = (query.casefold(), language)
    now = time.monotonic()

    cached = _cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    hl, gl, ceid = _locale(language)
    async with _lock:
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    NEWS_FEED_URL,
                    params={"q": query, "hl": hl, "gl": gl, "ceid": ceid},
                    headers={"User-Agent": "FlashFootballBot/1.0"},
                )
                response.raise_for_status()
            items = parse_news_feed(response.text, limit=limit)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Football news feed unavailable (%s).", type(exc).__name__)
            return ()

        _cache[key] = (time.monotonic() + NEWS_CACHE_TTL, items)
        return items
