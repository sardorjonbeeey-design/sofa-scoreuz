"""Collect and cache source-backed, structured league standings from TinyFish search results."""
import asyncio
import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.archive.archive_service import ArchiveService
from app.football.leagues import FEATURED_LEAGUES

logger = logging.getLogger(__name__)

TINYFISH_SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
STANDINGS_MAX_AGE_SECONDS = 24 * 60 * 60
REQUEST_DELAY_SECONDS = 2.1
PAGE_DELAY_SECONDS = 0.8
MAX_RESULTS_PER_LEAGUE = 5
MAX_PAGES_PER_LEAGUE = 2
MIN_TABLE_ROWS = 6

# Only fetch known public football publishers. Search results are external input;
# this allowlist prevents the collector from requesting arbitrary/internal URLs.
ALLOWED_SOURCE_DOMAINS = (
    "premierleague.com", "laliga.com", "bundesliga.com", "legaseriea.it",
    "legaseriea.com", "ligue1.com", "uefa.com", "the-afc.com",
    "espn.com", "worldfootball.net", "goal.com", "soccerway.com",
    "skysports.com", "bbc.com", "bbc.co.uk", "transfermarkt.com",
    "soccer24.com", "besoccer.com", "fotmob.com", "worldfootball.net",
)


def _safe_source_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            return None
    except ValueError:
        pass
    if not any(host == domain or host.endswith("." + domain) for domain in ALLOWED_SOURCE_DOMAINS):
        return None
    return value.strip()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", value.lower()).strip()


def _parse_int(value: str) -> int | None:
    match = re.search(r"[-+]?\d+", value.replace(",", ""))
    return int(match.group()) if match else None


def parse_standings_html(html_text: str, *, source_url: str, source_title: str,
                         league_id: int, league_name: str) -> dict[str, Any] | None:
    """Parse a genuine HTML standings table; reject partial or ambiguous results."""
    soup = BeautifulSoup(html_text, "html.parser")
    aliases = {
        "position": {"pos", "position", "rank", "#"},
        "team": {"team", "club", "squad", "teams"},
        "played": {"p", "pl", "played", "gp", "mp", "matches played"},
        "won": {"w", "won", "wins"},
        "drawn": {"d", "drawn", "draws", "t"},
        "lost": {"l", "lost", "losses"},
        "goals_for": {"gf", "goals for", "for"},
        "goals_against": {"ga", "goals against", "against"},
        "goal_difference": {"gd", "goal difference", "+/-", "diff"},
        "points": {"pts", "points"},
    }

    for table in soup.find_all("table"):
        header_row = None
        headers: list[str] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            labels = [_norm(cell.get_text(" ", strip=True)) for cell in cells]
            if any(label in aliases["team"] for label in labels) and (
                any(label in aliases["played"] for label in labels)
                and any(label in aliases["points"] for label in labels)
            ):
                header_row, headers = tr, labels
                break
        if header_row is None:
            continue

        col: dict[str, int] = {}
        for field, options in aliases.items():
            for idx, label in enumerate(headers):
                if label in options:
                    col[field] = idx
                    break
        if not {"team", "played", "points"}.issubset(col):
            continue

        rows: list[dict[str, Any]] = []
        seen_teams: set[str] = set()
        for tr in table.find_all("tr"):
            if tr is header_row:
                continue
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) <= max(col.values()):
                continue
            values = [cell.get_text(" ", strip=True) for cell in cells]
            team = values[col["team"]].strip()
            if not team or _norm(team) in aliases["team"] or len(team) > 100:
                continue
            # Ignore table footers, group labels, and rows without a real played/points pair.
            played = _parse_int(values[col["played"]])
            points = _parse_int(values[col["points"]])
            if played is None or points is None:
                continue
            normalized_team = _norm(team)
            if normalized_team in seen_teams:
                continue
            seen_teams.add(normalized_team)
            row: dict[str, Any] = {"team": team, "played": played, "points": points}
            for field in ("position", "won", "drawn", "lost", "goals_for", "goals_against", "goal_difference"):
                if field in col:
                    raw = values[col[field]].strip()
                    parsed = _parse_int(raw)
                    if field == "position" and parsed is None:
                        continue
                    if parsed is not None:
                        row[field] = parsed
            if "position" not in row:
                row["position"] = len(rows) + 1
            rows.append(row)

        if len(rows) < MIN_TABLE_ROWS:
            continue
        if len({row["team"] for row in rows}) != len(rows):
            continue
        rows.sort(key=lambda row: row["position"])
        return {
            "league_id": league_id,
            "league_name": league_name,
            "season": None,
            "rows": rows[:30],
            "source_url": source_url,
            "source_title": source_title[:250],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "verified_structure": True,
        }
    return None


class TinyFishStandingsCollector:
    """Search once per stale league, scrape at most two trusted sources, archive rows."""

    def __init__(self, *, api_key: str, archive: ArchiveService,
                 client: httpx.AsyncClient | None = None):
        self.api_key = api_key.strip()
        self.archive = archive
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(25.0), follow_redirects=True,
            headers={"User-Agent": "FlashFootballBot/1.0 (+standings archive)"},
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def collect_standings(self) -> None:
        pending = []
        previous_payloads: dict[int, dict[str, Any]] = {}
        now = datetime.now(timezone.utc)
        for league in FEATURED_LEAGUES:
            try:
                existing = await self.archive.get(
                    kind="tinyfish_standings", record_key=str(league.id),
                )
            except Exception:
                logger.exception("Could not inspect standings cache for %s.", league.name)
                continue
            if existing is not None:
                previous = existing.payload if isinstance(existing.payload, dict) else {}
                previous_payloads[league.id] = previous
                fetched_at = existing.fetched_at
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                fresh = now - fetched_at <= timedelta(seconds=STANDINGS_MAX_AGE_SECONDS)
                # Re-process older snippet-only records once after this parser upgrade,
                # but don't repeat the same failed extraction every scheduler tick.
                if fresh and previous.get("parser_version") == 2:
                    continue
            pending.append(league)

        if not pending:
            logger.info("TinyFish league standings cache is fresh; no searches needed.")
            return

        logger.info("TinyFish standings collection starting for %s leagues.", len(pending))
        saved = 0
        structured = 0
        for index, league in enumerate(pending):
            try:
                payload = await self._collect_one(league.id, league.name)
                if payload is not None:
                    previous = previous_payloads.get(league.id, {})
                    # Never replace a previously extracted table with search snippets
                    # just because a source is temporarily unavailable.
                    if not payload.get("table") and isinstance(previous.get("table"), dict):
                        payload["table"] = previous["table"]
                        payload["data_type"] = "structured_standings"
                        payload["last_table_refresh_failed_at"] = payload.get("queried_at")
                    await self.archive.upsert(
                        kind="tinyfish_standings", record_key=str(league.id),
                        payload=payload, source="tinyfish-search+html-table",
                    )
                    saved += 1
                    table = payload.get("table") if isinstance(payload.get("table"), dict) else {}
                    row_count = len(table.get("rows", []))
                    if table.get("verified_structure") and row_count >= MIN_TABLE_ROWS:
                        structured += 1
                        logger.info(
                            "Archived structured TinyFish standings for %s: %s rows from %s.",
                            league.name, row_count, table.get("source_url", "unknown source"),
                        )
                    else:
                        logger.warning(
                            "Archived TinyFish source evidence only for %s; no structured table extracted.",
                            league.name,
                        )
                else:
                    logger.warning("No valid structured standings table found for %s.", league.name)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    logger.error(
                        "TinyFish authorization failed (HTTP %s); stopping this collection run.",
                        exc.response.status_code,
                    )
                    return
                logger.exception("TinyFish standings collection failed for %s.", league.name)
            except (httpx.HTTPError, ValueError, TypeError):
                logger.exception("TinyFish standings collection failed for %s.", league.name)
            except Exception:
                logger.exception("Unexpected standings archive failure for %s.", league.name)
            if index + 1 < len(pending):
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        logger.info(
            "TinyFish standings collection finished: %s archives saved, %s structured tables extracted, %s leagues attempted.",
            saved, structured, len(pending),
        )

    async def _collect_one(self, league_id: int, league_name: str) -> dict[str, Any] | None:
        query = (
            f"{league_name} current {datetime.now(timezone.utc).year} "
            "league table standings position played won drawn lost goal difference points"
        )
        response = await self.client.get(
            TINYFISH_SEARCH_ENDPOINT,
            params={"query": query, "language": "en"},
            headers={"X-API-Key": self.api_key},
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
            url = _safe_source_url(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            results.append({
                "title": str(item.get("title") or league_name)[:250],
                "url": url[:1500],
                "snippet": str(item.get("snippet") or "")[:1200],
            })
            if len(results) >= MAX_RESULTS_PER_LEAGUE:
                break

        table = None
        pages_tried = 0
        for item in results:
            if pages_tried >= MAX_PAGES_PER_LEAGUE:
                break
            pages_tried += 1
            try:
                page = await self.client.get(item["url"])
                page.raise_for_status()
                table = parse_standings_html(
                    page.text, source_url=item["url"], source_title=item["title"],
                    league_id=league_id, league_name=league_name,
                )
                if table:
                    break
            except (httpx.HTTPError, ValueError):
                logger.warning("Could not parse standings source %s for league %s.", item["url"], league_name)
            if pages_tried < MAX_PAGES_PER_LEAGUE:
                await asyncio.sleep(PAGE_DELAY_SECONDS)

        now = datetime.now(timezone.utc).isoformat()
        return {
            "league_id": league_id,
            "league_name": league_name,
            "queried_at": now,
            "parser_version": 2,
            "results": results,
            "table": table,
            "data_type": "structured_standings" if table else "web_search_evidence_not_verified_table",
        }
