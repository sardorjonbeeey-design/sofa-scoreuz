"""Persistent archive storage shared by the main and supporter bots."""
import logging
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.storage.database import Database, StorageError, describe_db_error
from app.storage.models import ArchiveRecord, utc_now

logger = logging.getLogger(__name__)


class ArchiveService:
    """Idempotent persistent archive operations.

    Collectors fetch and validate data, then use this service to persist it.
    Telegram publishing and external API calls remain separate responsibilities.
    """
    def __init__(self, database: Database):
        self.database = database

    async def upsert(self, *, kind: str, record_key: str, payload: dict[str, Any],
                     source: str = "api-football") -> ArchiveRecord:
        kind = kind.strip().lower()
        record_key = record_key.strip()
        source = source.strip() or "unknown"
        if not kind or len(kind) > 32:
            raise ValueError("kind must contain 1-32 characters")
        if not record_key or len(record_key) > 160:
            raise ValueError("record_key must contain 1-160 characters")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        await self.database.ensure_schema()
        now = utc_now()
        try:
            async with self.database.session_factory() as session:
                result = await session.execute(select(ArchiveRecord).where(
                    ArchiveRecord.kind == kind, ArchiveRecord.record_key == record_key
                ))
                record = result.scalar_one_or_none()
                if record is None:
                    record = ArchiveRecord(kind=kind, record_key=record_key, payload=payload,
                                           source=source, fetched_at=now, created_at=now, updated_at=now)
                    session.add(record)
                else:
                    changed = record.payload != payload or record.source != source
                    record.payload = payload
                    record.source = source
                    record.fetched_at = now
                    if changed:
                        record.updated_at = now
                await session.commit()
                await session.refresh(record)
                return record
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.error("Archive upsert failed (%s): %s", type(exc).__name__, describe_db_error(exc))
            raise StorageError("Could not save archive record.") from exc

    async def get(self, *, kind: str, record_key: str,
                  max_age_seconds: int | None = None) -> ArchiveRecord | None:
        if max_age_seconds is not None and max_age_seconds < 0:
            raise ValueError("max_age_seconds cannot be negative")
        await self.database.ensure_schema()
        try:
            async with self.database.session_factory() as session:
                result = await session.execute(select(ArchiveRecord).where(
                    ArchiveRecord.kind == kind.strip().lower(),
                    ArchiveRecord.record_key == record_key.strip()
                ))
                record = result.scalar_one_or_none()
                if record is None:
                    return None
                if max_age_seconds is not None:
                    fetched_at = record.fetched_at
                    if fetched_at.tzinfo is None:
                        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                    if utc_now() - fetched_at > timedelta(seconds=max_age_seconds):
                        return None
                return record
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.error("Archive read failed (%s): %s", type(exc).__name__, describe_db_error(exc))
            raise StorageError("Could not read archive record.") from exc

    async def list_records(self, *, kind: str, limit: int = 100) -> list[ArchiveRecord]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        await self.database.ensure_schema()
        try:
            async with self.database.session_factory() as session:
                result = await session.execute(select(ArchiveRecord)
                    .where(ArchiveRecord.kind == kind.strip().lower())
                    .order_by(ArchiveRecord.fetched_at.desc()).limit(limit))
                return list(result.scalars().all())
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.error("Archive list failed (%s): %s", type(exc).__name__, describe_db_error(exc))
            raise StorageError("Could not list archive records.") from exc

    async def archive_fixture(self, fixture) -> None:
        from dataclasses import asdict
        await self.upsert(kind="fixture", record_key=str(fixture.id),
                          payload=asdict(fixture), source="api-football")

    async def get_archived_fixture(self, fixture_id: int):
        record = await self.get(kind="fixture", record_key=str(fixture_id))
        return record.payload if record else None
