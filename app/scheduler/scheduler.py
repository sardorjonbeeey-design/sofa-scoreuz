from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.archive.tinyfish_foundation import TinyFishFoundationCollector
from app.archive.tinyfish_standings import TinyFishStandingsCollector
from app.config import Settings


def create_scheduler(
    settings: Settings,
    foundation_collector: TinyFishFoundationCollector | None = None,
    standings_collector: TinyFishStandingsCollector | None = None,
) -> AsyncIOScheduler:
    """Schedule slow-changing archive enrichment, never periodic provider polling."""
    scheduler = AsyncIOScheduler()

    if foundation_collector is not None:
        scheduler.add_job(
            foundation_collector.collect_foundation,
            trigger="interval",
            seconds=settings.archive_foundation_interval_seconds,
            id="archive-tinyfish-foundation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if standings_collector is not None:
        scheduler.add_job(
            standings_collector.collect_standings,
            trigger="interval",
            seconds=settings.archive_foundation_interval_seconds,
            id="archive-tinyfish-standings",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    return scheduler
