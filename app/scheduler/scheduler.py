from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.archive.collector import ArchiveCollector
from app.config import Settings


def create_scheduler(
    settings: Settings,
    archive_collector: ArchiveCollector | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    if archive_collector is not None:
        scheduler.add_job(
            archive_collector.collect_live,
            trigger="interval",
            seconds=settings.archive_live_interval_seconds,
            id="archive-live-fixtures",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            archive_collector.collect_fixtures,
            trigger="interval",
            seconds=settings.archive_fixtures_interval_seconds,
            id="archive-todays-fixtures",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    return scheduler
