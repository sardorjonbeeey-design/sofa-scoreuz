from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.archive.gemini_foundation as foundation
from app.archive.archive_service import ArchiveService
from app.scheduler.scheduler import create_scheduler
from app.storage.database import Database
from tests.conftest import make_settings


def sqlite_url(path) -> str:
    return f"sqlite+aiosqlite:///{path}"


async def test_gemini_foundation_skips_fresh_profiles(tmp_path, monkeypatch):
    database = Database(sqlite_url(tmp_path / "archive.db"))
    archive = ArchiveService(database)
    telegram = SimpleNamespace(send_message=AsyncMock())
    client = SimpleNamespace(post=AsyncMock(side_effect=AssertionError("should not call Gemini")))
    monkeypatch.setattr(
        foundation,
        "SEED_ENTITIES",
        ({"kind": "club", "key": "test-club", "name": "Test Club"},),
    )
    await archive.upsert(
        kind="foundation_club",
        record_key="test-club",
        payload={"name": "Test Club", "overview": "A saved profile."},
        source="gemini-google-search",
    )
    collector = foundation.GeminiFoundationCollector(
        api_key="test-key",
        archive=archive,
        telegram=telegram,
        channel_id=-100123,
        client=client,
    )
    try:
        await collector.collect_foundation()
        client.post.assert_not_awaited()
        telegram.send_message.assert_not_awaited()
    finally:
        await database.dispose()


def test_extract_json_accepts_fenced_json():
    result = foundation._extract_json("""```json\n{"profiles": []}\n```""")
    assert result == {"profiles": []}


def test_foundation_scheduler_has_no_api_football_jobs():
    collector = SimpleNamespace(collect_foundation=AsyncMock())
    scheduler = create_scheduler(make_settings(), collector)
    try:
        jobs = scheduler.get_jobs()
        assert [job.id for job in jobs] == ["archive-gemini-foundation"]
        assert jobs[0].trigger.interval.total_seconds() == 86400
    finally:
        scheduler.shutdown(wait=False)
