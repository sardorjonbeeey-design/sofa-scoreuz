from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Data refresh and live-match jobs will be added here.

    return scheduler