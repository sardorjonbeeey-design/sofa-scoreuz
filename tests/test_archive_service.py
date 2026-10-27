from datetime import timedelta
import pytest

from app.archive.archive_service import ArchiveService
from app.storage.database import Database


def sqlite_url(path) -> str:
    return f"sqlite+aiosqlite:///{path}"


@pytest.fixture
async def archive(tmp_path):
    database = Database(sqlite_url(tmp_path / "archive.db"))
    service = ArchiveService(database)
    yield service
    await database.dispose()


async def test_upsert_is_idempotent_and_updates_freshness(archive):
    first = await archive.upsert(kind="fixture", record_key="123",
                                 payload={"home": "Barcelona", "status": "NS"})
    second = await archive.upsert(kind="fixture", record_key="123",
                                  payload={"home": "Barcelona", "status": "FT"})
    assert first.id == second.id
    assert second.payload["status"] == "FT"
    assert second.fetched_at >= first.fetched_at
    assert len(await archive.list_records(kind="fixture")) == 1


async def test_get_can_reject_stale_records(archive):
    record = await archive.upsert(kind="team", record_key="barcelona", payload={"id": 529})
    async with archive.database.session_factory() as session:
        row = await session.get(type(record), record.id)
        row.fetched_at = row.fetched_at - timedelta(days=2)
        await session.commit()
    assert await archive.get(kind="team", record_key="barcelona", max_age_seconds=60) is None
    assert await archive.get(kind="team", record_key="barcelona") is not None


async def test_kind_and_key_are_normalized(archive):
    record = await archive.upsert(kind=" Team ", record_key=" 529 ", payload={"name": "Barcelona"})
    assert record.kind == "team" and record.record_key == "529"
    assert (await archive.get(kind="TEAM", record_key="529")).id == record.id


async def test_invalid_inputs_are_rejected(archive):
    with pytest.raises(ValueError):
        await archive.upsert(kind="", record_key="1", payload={})
    with pytest.raises(ValueError):
        await archive.upsert(kind="fixture", record_key="", payload={})
    with pytest.raises(TypeError):
        await archive.upsert(kind="fixture", record_key="1", payload=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await archive.list_records(kind="fixture", limit=0)
