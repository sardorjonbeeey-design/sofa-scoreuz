"""Free TinyFish web-search foundation archive collector.

This collector uses TinyFish Search results directly. It does not use an LLM
and does not call API-Football. Profiles are evidence snippets with source URLs,
not AI-written summaries; unknown fields are left empty rather than guessed.
"""
import asyncio
import html
import logging
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot
import httpx

from app.archive.archive_service import ArchiveService

logger = logging.getLogger(__name__)

TINYFISH_SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
PROFILE_MAX_AGE_SECONDS = 90 * 24 * 60 * 60
REQUEST_DELAY_SECONDS = 2.1

SEED_ENTITIES: tuple[dict[str, str], ...] = (
    {"kind": "competition", "key": "uefa-champions-league", "name": "UEFA Champions League"},
    {"kind": "competition", "key": "uefa-europa-league", "name": "UEFA Europa League"},
    {"kind": "competition", "key": "premier-league", "name": "English Premier League"},
    {"kind": "competition", "key": "la-liga", "name": "Spanish La Liga"},
    {"kind": "competition", "key": "serie-a", "name": "Italian Serie A"},
    {"kind": "competition", "key": "bundesliga", "name": "German Bundesliga"},
    {"kind": "competition", "key": "ligue-1", "name": "French Ligue 1"},
    {"kind": "competition", "key": "saudi-pro-league", "name": "Saudi Pro League"},
    {"kind": "competition", "key": "turkish-super-lig", "name": "Turkish Süper Lig"},
    {"kind": "competition", "key": "russian-premier-league", "name": "Russian Premier League"},
    {"kind": "competition", "key": "uzbek-super-league", "name": "Uzbekistan Super League"},
    {"kind": "club", "key": "real-madrid", "name": "Real Madrid"},
    {"kind": "club", "key": "barcelona", "name": "FC Barcelona"},
    {"kind": "club", "key": "manchester-city", "name": "Manchester City"},
    {"kind": "club", "key": "manchester-united", "name": "Manchester United"},
    {"kind": "club", "key": "liverpool", "name": "Liverpool FC"},
    {"kind": "club", "key": "arsenal", "name": "Arsenal FC"},
    {"kind": "club", "key": "chelsea", "name": "Chelsea FC"},
    {"kind": "club", "key": "bayern-munich", "name": "FC Bayern Munich"},
    {"kind": "club", "key": "borussia-dortmund", "name": "Borussia Dortmund"},
    {"kind": "club", "key": "paris-saint-germain", "name": "Paris Saint-Germain"},
    {"kind": "club", "key": "juventus", "name": "Juventus"},
    {"kind": "club", "key": "inter-milan", "name": "Inter Milan"},
    {"kind": "club", "key": "galatasaray", "name": "Galatasaray"},
    {"kind": "club", "key": "al-hilal", "name": "Al-Hilal"},
    {"kind": "club", "key": "al-nassr", "name": "Al-Nassr"},
    {"kind": "club", "key": "pakhtakor", "name": "Pakhtakor Tashkent"},
    {"kind": "club", "key": "uzbekistan-national-team", "name": "Uzbekistan men's national football team"},
)


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return value.strip()


class TinyFishFoundationCollector:
    """Research missing/stale foundation profiles using TinyFish Search."""

    def __init__(
        self,
        *,
        api_key: str,
        archive: ArchiveService,
        telegram: Bot,
        channel_id: int,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key.strip()
        self.archive = archive
        self.telegram = telegram
        self.channel_id = channel_id
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def collect_foundation(self) -> None:
        pending: list[dict[str, str]] = []
        for entity in SEED_ENTITIES:
            existing = await self.archive.get(
                kind=f"foundation_{entity['kind']}",
                record_key=entity["key"],
                max_age_seconds=PROFILE_MAX_AGE_SECONDS,
            )
            if existing is None:
                pending.append(entity)

        if not pending:
            logger.info("Foundational football archive is fresh; no TinyFish searches needed.")
            return

        logger.info("TinyFish foundation collection starting for %s entities.", len(pending))
        succeeded = 0
        for index, entity in enumerate(pending):
            try:
                profile = await self._research_entity(entity)
                if profile is None:
                    continue
                await self.archive.upsert(
                    kind=f"foundation_{entity['kind']}",
                    record_key=entity["key"],
                    payload=profile,
                    source="tinyfish-search",
                )
                await self._publish_digest(profile)
                succeeded += 1
                logger.info("Archived TinyFish foundation profile %s.", entity["key"])
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning(
                    "TinyFish foundation search failed for %s (%s); continuing.",
                    entity["key"],
                    type(exc).__name__,
                )
            except Exception:
                logger.exception("Unexpected TinyFish archive failure for %s.", entity["key"])
            if index + 1 < len(pending):
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

        logger.info(
            "TinyFish foundation collection finished: %s/%s profiles archived.",
            succeeded,
            len(pending),
        )

    async def _research_entity(self, entity: dict[str, str]) -> dict[str, Any] | None:
        query = f'{entity["name"]} official website history facts football'
        response = await self.client.get(
            TINYFISH_SEARCH_ENDPOINT,
            params={"query": query, "language": "en"},
            headers={"X-API-Key": self.api_key},
        )
        if response.status_code >= 400:
            provider_message = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    provider_message = str(body.get("message") or body.get("error") or "")[:250]
            except ValueError:
                pass
            logger.warning(
                "TinyFish search failed with HTTP %s (message=%s).",
                response.status_code,
                provider_message or "no provider message",
            )
            response.raise_for_status()

        body = response.json()
        raw_results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(raw_results, list):
            raise ValueError("TinyFish returned an unexpected search payload")

        sources: list[dict[str, str]] = []
        snippets: list[str] = []
        seen_urls: set[str] = set()
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            url = _https_url(result.get("url"))
            snippet = str(result.get("snippet") or "").strip()
            title = str(result.get("title") or url or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append({"url": url, "title": title[:200] or url})
            if snippet:
                snippets.append(snippet[:500])
            if len(sources) >= 5:
                break

        if not snippets or not sources:
            logger.warning("TinyFish returned no usable snippets for %s.", entity["key"])
            return None

        # No model is used here: retain the provider's excerpts and citations
        # verbatim instead of fabricating a synthesized overview.
        overview = "Search excerpts: " + " ".join(snippets[:3])
        return {
            "key": entity["key"],
            "entity_type": entity["kind"],
            "name": entity["name"],
            "country": None,
            "founded_or_established": None,
            "overview": overview[:1800],
            "facts": snippets[:5],
            "aliases": [],
            "sources": sources,
            "research_method": "TinyFish Web Search API; source snippets, not AI-generated summary",
        }

    async def _publish_digest(self, profile: dict[str, Any]) -> None:
        entity_type = "Competition" if profile["entity_type"] == "competition" else "Club / team"
        lines = [
            "📚 <b>Football knowledge archive</b>",
            f"<b>{html.escape(profile['name'])}</b> · {entity_type}",
            html.escape(profile["overview"][:1800]),
        ]
        source_list = profile.get("sources") or []
        if source_list:
            lines.append("Sources: " + " · ".join(
                f'<a href="{html.escape(item["url"], quote=True)}">{html.escape(item["title"])}</a>'
                for item in source_list[:3]
            ))
        message = "\n\n".join(lines)
        try:
            await self.telegram.send_message(
                chat_id=self.channel_id,
                text=message[:3900],
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Could not publish TinyFish foundation digest for %s.", profile["key"])
