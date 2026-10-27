"""Gemini-assisted foundational football knowledge archive.

This collector intentionally does not call API-Football. It researches stable
club/competition profiles with Gemini Search grounding, stores them in the
shared PostgreSQL archive, and publishes compact grouped digests to Telegram.
"""
import asyncio
import html
import json
import logging
import re
from typing import Any

import httpx

from app.archive.archive_service import ArchiveService
from aiogram import Bot

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
PROFILE_MAX_AGE_SECONDS = 90 * 24 * 60 * 60
BATCH_SIZE = 5

# A deliberately small starter catalogue. Extend it through data/config rather
# than making live-provider calls to discover the archive's seed entities.
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


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    value = json.loads(cleaned)
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), list):
        raise ValueError("Gemini returned an unexpected profile payload")
    return value


def _grounding_sources(candidate: dict[str, Any]) -> list[dict[str, str]]:
    metadata = candidate.get("groundingMetadata") or {}
    sources: list[dict[str, str]] = []
    for chunk in metadata.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        url = web.get("uri")
        title = web.get("title")
        if isinstance(url, str) and url.startswith("https://"):
            item = {"url": url, "title": str(title or url)[:200]}
            if item not in sources:
                sources.append(item)
    return sources[:10]


class GeminiFoundationCollector:
    """Research missing/stale base profiles and archive them idempotently."""

    def __init__(
        self,
        *,
        api_key: str,
        archive: ArchiveService,
        telegram: Bot,
        channel_id: int,
        timezone: str = "Asia/Tashkent",
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key.strip()
        self.archive = archive
        self.telegram = telegram
        self.channel_id = channel_id
        self.timezone = timezone
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def collect_foundation(self) -> None:
        pending: list[dict[str, str]] = []
        for entity in SEED_ENTITIES:
            kind = f"foundation_{entity['kind']}"
            existing = await self.archive.get(
                kind=kind,
                record_key=entity["key"],
                max_age_seconds=PROFILE_MAX_AGE_SECONDS,
            )
            if existing is None:
                pending.append(entity)

        if not pending:
            logger.info("Foundational football archive is fresh; no Gemini calls needed.")
            return

        # One grounded Gemini request per small batch; no API-Football requests.
        for offset in range(0, len(pending), BATCH_SIZE):
            batch = pending[offset:offset + BATCH_SIZE]
            try:
                profiles, sources = await self._research_batch(batch)
                by_key = {str(item.get("key", "")).strip(): item for item in profiles if isinstance(item, dict)}
                stored: list[dict[str, Any]] = []
                for entity in batch:
                    profile = by_key.get(entity["key"])
                    if profile is None:
                        logger.warning("Gemini omitted foundation profile %s.", entity["key"])
                        continue
                    name = str(profile.get("name") or "").strip()
                    overview = str(profile.get("overview") or "").strip()
                    if not name or not overview:
                        logger.warning("Gemini returned an incomplete foundation profile for %s.", entity["key"])
                        continue
                    payload = {
                        "key": entity["key"],
                        "entity_type": entity["kind"],
                        "name": name[:200],
                        "country": _optional_text(profile.get("country")),
                        "founded_or_established": _optional_text(profile.get("founded_or_established")),
                        "overview": overview[:1800],
                        "facts": _text_list(profile.get("facts"), limit=6),
                        "aliases": _text_list(profile.get("aliases"), limit=8),
                        "sources": _profile_sources(profile.get("sources"), sources),
                        "research_method": "Gemini with Google Search grounding",
                    }
                    await self.archive.upsert(
                        kind=f"foundation_{entity['kind']}",
                        record_key=entity["key"],
                        payload=payload,
                        source="gemini-google-search",
                    )
                    stored.append(payload)

                if stored:
                    await self._publish_digest(stored)
                # Be gentle with free-tier quotas and avoid a burst of requests.
                if offset + BATCH_SIZE < len(pending):
                    await asyncio.sleep(2)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.warning(
                    "Gemini foundation batch failed (%s); later batches will still be attempted.",
                    type(exc).__name__,
                )
            except Exception:
                logger.exception("Unexpected failure in Gemini foundation batch.")

    async def _research_batch(
        self, batch: list[dict[str, str]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        entities = [{"key": item["key"], "type": item["kind"], "name": item["name"]} for item in batch]
        prompt = (
            "Research these football entities using Google Search grounding. "
            "Return only valid JSON with top-level key profiles. Return exactly one profile "
            "for each requested key, preserving its key. Each profile must contain key, name, "
            "country (string or null), founded_or_established (string or null), overview "
            "(2-4 factual sentences), facts (up to 6 concise factual strings), aliases "
            "(up to 8 official/common names), and sources (array of {title,url}). "
            "Prefer official club, competition, federation, or league sources. Do not guess: "
            "use null or omit a fact when it cannot be verified. Do not include current scores, "
            "fixtures, standings, transfer rumours, or other rapidly changing data. "
            "Requested entities: " + json.dumps(entities, ensure_ascii=False)
        )
        response = await self.client.post(
            GEMINI_ENDPOINT,
            headers={"x-goog-api-key": self.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
            },
        )
        if response.status_code >= 400:
            # Never log the request URL, request headers, or API key.
            logger.warning("Gemini research request failed with HTTP %s.", response.status_code)
            response.raise_for_status()
        body = response.json()
        candidates = body.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidate")
        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts") or [])
        text = "\n".join(str(part.get("text", "")) for part in parts if part.get("text"))
        if not text:
            raise ValueError("Gemini returned no text")
        parsed = _extract_json(text)
        return parsed["profiles"], _grounding_sources(candidate)

    async def _publish_digest(self, profiles: list[dict[str, Any]]) -> None:
        header = "📚 <b>Football knowledge archive</b>"
        blocks: list[str] = []
        for profile in profiles:
            entity_type = "Competition" if profile["entity_type"] == "competition" else "Club / team"
            lines = [f"<b>{html.escape(profile['name'])}</b> · {entity_type}"]
            if profile.get("country"):
                lines.append(f"Country: {html.escape(profile['country'])}")
            if profile.get("founded_or_established"):
                lines.append(f"Founded / established: {html.escape(profile['founded_or_established'])}")
            lines.append(html.escape(profile["overview"][:900]))
            for fact in profile.get("facts", [])[:3]:
                lines.append(f"• {html.escape(fact)}")
            source_list = profile.get("sources") or []
            if source_list:
                lines.append("Sources: " + " · ".join(
                    f'<a href="{html.escape(item["url"], quote=True)}">{html.escape(item["title"])}</a>'
                    for item in source_list[:2]
                ))
            blocks.append("\\n".join(lines))

        # Split at profile boundaries so every Telegram HTML message stays
        # within the limit and one long Gemini response cannot break markup.
        messages: list[str] = []
        current = header
        for block in blocks:
            candidate = current + "\\n\\n" + block
            if len(candidate) > 3800 and current != header:
                messages.append(current)
                current = header + "\\n\\n" + block
            else:
                current = candidate
        if current != header:
            messages.append(current)

        for message in messages:
            try:
                await self.telegram.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Could not publish Gemini foundation digest to Telegram.")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:200] or None


def _text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value if str(item).strip()][:limit]


def _profile_sources(value: Any, grounded: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or url).strip()
            if url.startswith("https://") and item not in result:
                result.append({"url": url, "title": title[:200]})
    # Grounding links are the provenance fallback when the model's JSON omits URLs.
    if not result:
        result = grounded[:5]
    return result[:5]
