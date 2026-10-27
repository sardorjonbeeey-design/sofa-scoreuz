"""Scheduled collector shared by the main bot and Telegram archive channel."""
import logging
from html import escape
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.archive.archive_service import ArchiveService
from app.football.provider import FootballProvider

logger = logging.getLogger(__name__)


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class ArchiveCollector:
    """Fetch structured data once, persist it, and publish meaningful changes."""

    def __init__(
        self,
        *,
        provider: FootballProvider,
        archive: ArchiveService,
        telegram: Bot,
        channel_id: int,
        timezone: str = "Asia/Tashkent",
    ):
        self.provider = provider
        self.archive = archive
        self.telegram = telegram
        self.channel_id = channel_id
        self.timezone = timezone
        self._tz = ZoneInfo(timezone)

    async def collect_fixtures(self) -> None:
        """Refresh today's fixtures at most once per six-hour freshness window."""
        today = datetime.now(self._tz).date()
        key = f"fixtures:{today.isoformat()}:{self.timezone}"
        if await self.archive.get(
            kind="collector_state", record_key=key, max_age_seconds=21600
        ):
            return

        fixtures = await self.provider.get_fixtures_by_date(today, self.timezone)
        for fixture in fixtures:
            await self.archive.archive_fixture(fixture)

        await self.archive.upsert(
            kind="collector_state",
            record_key=key,
            payload={"date": today.isoformat(), "count": len(fixtures)},
            source="api-football",
        )

        # One digest per local day; do not post each fixture as a separate message.
        digest_key = f"daily-fixtures:{today.isoformat()}:{self.timezone}"
        if not await self.archive.get(kind="archive_digest", record_key=digest_key):
            lines = [
                f"📅 <b>Bugungi futbol — {today.isoformat()}</b>",
                f"Jami uchrashuvlar: <b>{len(fixtures)}</b>",
            ]
            for fixture in fixtures[:35]:
                kickoff = fixture.start_time.astimezone(self._tz).strftime("%H:%M")
                lines.append(
                    f"• {kickoff} — {escape(fixture.home_team.name)} – {escape(fixture.away_team.name)}"
                    f" ({escape(fixture.competition)})"
                )
            if len(fixtures) > 35:
                lines.append(f"… va yana {len(fixtures) - 35} ta uchrashuv.")
            try:
                await self.telegram.send_message(
                    chat_id=self.channel_id,
                    text="\n".join(lines),
                    disable_web_page_preview=True,
                )
                await self.archive.upsert(
                    kind="archive_digest",
                    record_key=digest_key,
                    payload={"date": today.isoformat(), "count": len(fixtures)},
                    source="supporter-bot",
                )
            except Exception:
                logger.exception("Could not publish daily fixture digest.")

        logger.info("Archived %s fixtures for %s.", len(fixtures), today)

    async def collect_live(self) -> None:
        """Persist live snapshots and publish only new/changed match states."""
        fixtures = await self.provider.get_live_fixtures()
        for fixture in fixtures:
            key = str(fixture.id)
            previous = await self.archive.get(kind="fixture", record_key=key)
            payload = _json_value(fixture)
            await self.archive.upsert(
                kind="fixture",
                record_key=key,
                payload=payload,
                source="api-football",
            )
            old = previous.payload if previous else None
            if old is not None and (
                old.get("status") == payload.get("status")
                and old.get("home_goals") == payload.get("home_goals")
                and old.get("away_goals") == payload.get("away_goals")
            ):
                continue

            score = "—"
            if fixture.home_goals is not None and fixture.away_goals is not None:
                score = f"{fixture.home_goals}–{fixture.away_goals}"
            minute = f" ({fixture.elapsed}') " if fixture.elapsed is not None else " "
            message = (
                f"⚽ <b>{escape(fixture.competition)}</b>\n"
                f"{escape(fixture.home_team.name)} {score} {escape(fixture.away_team.name)}\n"
                f"<b>{fixture.status}</b>{minute}"
            )
            try:
                await self.telegram.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Could not publish live update for fixture %s.", fixture.id)

        logger.info("Archived %s live fixtures.", len(fixtures))
