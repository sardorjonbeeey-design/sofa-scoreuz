"""Cached TinyFish search evidence for league standings.

TinyFish Search is a web-search API, not a structured football-data API.
Records therefore retain source-backed snippets and links; they must not be
presented as a complete table unless the source result actually contains one.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.archive.archive_service import ArchiveService
from app.football.leagues import FEATURED_LEAGUES

logger = logging.getLogger(__name__)

TINYFISH_SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
STANDINGS_MAX_AGE_SECONDS = 24 * 60 * 60
REQUEST_DELAY_SECONDS = 2.1
MAX_RESULTS_PER_LEAGUE = 5


class TinyFishStandingsCollector:
    """Collect source-linked standings search results for configured leagues."""

    def __init__(
        self,
        *,
        api_key: str,
        archive: ArchiveService,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key.strip()
        self.archive = archive
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def collect_standings(self) -> None:
        pending = []
        for league in FEATURED_LEAGUES:
            existing = await self.archive.get(
                kind="tinyfish_standings",
                record_key=str(league.id),
                max_age_seconds=STANDINGS_MAX_AGE_SECONDS,
            )
            if existing is None:
                pending.append(league)

        if not pending:
            logger.info("TinyFish league standings search cache is fresh; no searches needed.")
            return

        logger.info("TinyFish standings collection starting for %s leagues.", len(pending))
        succeeded = 0
        for index, league in enumerate(pending):
            try:
                query = (
                    f"{league.name} current {datetime.now(timezone.utc).year} "
                    "league table standings points played goal difference official"
                )
                response = await self.client.get(
                    TINYFISH_SEARCH_ENDPOINT,
                    params={"query": query, "language": "en"},
                    headers={"X-API-Key": self.api_key},
                )
                if response.status_code >= 400:
                    message = ""
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            message = str(body.get("message") or body.get("error") or "")[:200]
                    except ValueError:
                        pass
                    logger.warning(
                        "TinyFish standings search failed for league %s: HTTP %s (%s).",
                        league.id, response.status_code, message or "no provider message",
                    )
                    response.raise_for_status()

                body = response.json()
                raw_results = body.get("results") if isinstance(body, dict) else None
                if not isinstance(raw_results, list):
                    raise ValueError("TinyFish returned an unexpected search payload")

                results: list[dict[str, str]] = []
                seen: set[str] = set()
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    title = item.get("title")
                    snippet = item.get("snippet")
                    if not isinstance(url, str) or not url.startswith("https://"):
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    results.append({
                        "title": str(title or league.name)[:250],
                        "url": url[:1500],
                        "snippet": str(snippet or "")[:1200],
                    })
                    if len(results) >= MAX_RESULTS_PER_LEAGUE:
                        break

                payload: dict[str, Any] = {
                    "league_id": league.id,
                    "league_name": league.name,
                    "queried_at": datetime.now(timezone.utc).isoformat(),
                    "results": results,
                    "data_type": "web_search_evidence_not_verified_table",
                }
                await self.archive.upsert(
                    kind="tinyfish_standings",
                    record_key=str(league.id),
                    payload=payload,
                    source="tinyfish-search",
                )
                succeeded += 1
                logger.info(
                    "Archived TinyFish standings search for %s (%s results).",
                    league.name, len(results),
                )
            except (httpx.HTTPError, ValueError, TypeError):
                logger.exception("TinyFish standings search failed for league %s.", league.name)
            except Exception:
                logger.exception("Unexpected TinyFish standings archive failure for %s.", league.name)

            if index + 1 < len(pending):
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

        logger.info("TinyFish standings collection finished: %s/%s leagues.", succeeded, len(pending))
