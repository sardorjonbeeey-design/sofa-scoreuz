from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.archive.tinyfish_foundation as foundation
from app.archive.archive_service import ArchiveService
from app.scheduler.scheduler import create_scheduler
from app.storage.database import Database
from tests.conftest import make_settings


def sqlite_url(path) -> str:
    return f"sqlite+aiosqlite:///{path}"


async def test_tinyfish_foundation_skips_fresh_profiles(tmp_path, monkeypatch):
    database = Database(sqlite_url(tmp_path / "archive.db"))
    archive = ArchiveService(database)
    telegram = SimpleNamespace(send_message=AsyncMock())
    client = SimpleNamespace(get=AsyncMock(side_effect=AssertionError("should not search")))
    monkeypatch.setattr(
        foundation,
        "SEED_ENTITIES",
        ({"kind": "club", "key": "test-club", "name": "Test Club"},),
    )
    await archive.upsert(
        kind="foundation_club",
        record_key="test-club",
        payload={"name": "Test Club", "overview": "A saved profile."},
        source="tinyfish-search",
    )
    collector = foundation.TinyFishFoundationCollector(
        api_key="test-key",
        archive=archive,
        telegram=telegram,
        channel_id=-100123,
        client=client,
    )
    try:
        await collector.collect_foundation()
        client.get.assert_not_awaited()
        telegram.send_message.assert_not_awaited()
    finally:
        await database.dispose()


async def test_tinyfish_search_results_become_cited_profile():
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "results": [
                {
                    "title": "Official club",
                    "url": "https://example.com/club",
                    "snippet": "The club was established in 1900.",
                },
                {
                    "title": "Unsafe URL",
                    "url": "http://example.com/club",
                    "snippet": "This source must be ignored.",
                },
            ]
        },
        raise_for_status=lambda: None,
    )
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    collector = foundation.TinyFishFoundationCollector(
        api_key="test-key",
        archive=SimpleNamespace(),
        telegram=SimpleNamespace(),
        channel_id=-100123,
        client=client,
    )
    profile = await collector._research_entity(
        {"kind": "club", "key": "test-club", "name": "Test Club"}
    )
    assert profile is not None
    assert profile["name"] == "Test Club"
    assert profile["sources"] == [
        {"url": "https://example.com/club", "title": "Official club"}
    ]
    assert "established in 1900" in profile["overview"]
    assert profile["country"] is None
    client.get.assert_awaited_once()
    assert client.get.await_args.kwargs["headers"] == {"X-API-Key": "test-key"}


def test_foundation_scheduler_has_no_api_football_jobs():
    collector = SimpleNamespace(collect_foundation=AsyncMock())
    scheduler = create_scheduler(make_settings(), collector)
    jobs = scheduler.get_jobs()
    assert [job.id for job in jobs] == ["archive-tinyfish-foundation"]
    assert jobs[0].trigger.interval.total_seconds() == 86400
