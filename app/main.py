import asyncio
import logging
import os
from contextlib import AsyncExitStack

from aiohttp import web

from app.bot.bot import create_bot, create_dispatcher
from app.archive.archive_service import ArchiveService
from app.archive.gemini_foundation import GeminiFoundationCollector
from app.cache.cache import MemoryCache
from app.config import Settings, get_settings
from app.football.api_football import ApiFootballProvider
from app.football.caching import CachingFootballProvider
from app.football.service import CacheTimes, FootballService
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import TeamResolver
from app.scheduler.scheduler import create_scheduler
from app.storage.factory import create_store

logger = logging.getLogger(__name__)

DEFAULT_PORT = 10000


async def health_check(request):
    return web.Response(text="Flash Football is running")


async def start_web_server(port: int | None = None) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    if port is None:
        port = _port_from_env()

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    return runner


def _port_from_env() -> int:
    raw = os.getenv("PORT", "").strip()

    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        logger.warning("PORT is not a valid integer; using %s.", DEFAULT_PORT)
        return DEFAULT_PORT


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level.upper(),
            logging.INFO,
        ),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def run_application(
    settings: Settings,
    port: int | None = None,
) -> None:
    """Start every component, run polling, and shut down cleanly.

    Components are registered on an ``AsyncExitStack`` as they start,
    so they are released in reverse order (scheduler -> bot session ->
    football client -> database -> health server) even if a later
    step fails or polling is interrupted by SIGTERM/SIGINT.
    """
    async with AsyncExitStack() as stack:
        # Bind the health-check port first: hosting platforms expect
        # the service to listen quickly, even while the database is
        # still being contacted.
        web_runner = await start_web_server(port)
        stack.push_async_callback(web_runner.cleanup)

        store = await create_store(settings)
        stack.push_async_callback(store.close)

        resolver = None
        service = None
        provider = None

        if settings.api_football_key:
            provider = CachingFootballProvider(
                ApiFootballProvider(settings.api_football_key),
                MemoryCache(max_items=2000),
            )
            stack.push_async_callback(provider.close)
            resolver = TeamResolver(provider)
            service = FootballService(
                provider,
                timezone=settings.display_timezone,
                times=CacheTimes(
                    live=settings.live_cache_ttl,
                    fixtures=settings.fixtures_cache_ttl,
                ),
            )
        else:
            logger.warning(
                "API_FOOTBALL_KEY is not set: team search, live scores, "
                "fixtures and standings are disabled."
            )

        bot = create_bot(settings.bot_token)
        stack.push_async_callback(bot.session.close)

        dispatcher = create_dispatcher(
            settings,
            store=store,
            resolver=resolver,
            directory=TeamDirectory(),
            service=service,
        )

        foundation_collector = None
        supporter_bot = None
        archive_database = getattr(store, "database", None)
        if settings.supporter_bot_token and settings.archive_channel_id is not None:
            if not settings.gemini_api_key or archive_database is None:
                logger.warning(
                    "Supporter Bot foundation archive requires GEMINI_API_KEY "
                    "and a persistent DATABASE_URL. Gemini archive automation is disabled."
                )
            else:
                supporter_bot = create_bot(settings.supporter_bot_token)
                stack.push_async_callback(supporter_bot.session.close)
                foundation_collector = GeminiFoundationCollector(
                    api_key=settings.gemini_api_key,
                    archive=ArchiveService(archive_database),
                    telegram=supporter_bot,
                    channel_id=settings.archive_channel_id,
                    timezone=settings.display_timezone,
                )
                stack.push_async_callback(foundation_collector.close)
        elif settings.supporter_bot_token or settings.archive_channel_id is not None:
            logger.warning(
                "Supporter Bot archive is only partially configured. Set both "
                "SUPPORTER_BOT_TOKEN and ARCHIVE_CHANNEL_ID to enable it."
            )

        # The Supporter Bot's scheduled archive path is Gemini-only. It does
        # not poll API-Football for fixtures/live matches on startup or a timer.
        scheduler = create_scheduler(settings, foundation_collector)
        scheduler.start()
        if foundation_collector is not None:
            async def run_initial_foundation_job() -> None:
                try:
                    await foundation_collector.collect_foundation()
                except Exception:
                    logger.exception("Initial Gemini foundation archive collection failed.")

            initial_archive_task = asyncio.create_task(run_initial_foundation_job())
            stack.callback(initial_archive_task.cancel)
        stack.callback(
            lambda: scheduler.shutdown(wait=False)
            if scheduler.running
            else None
        )

        logger.info("Starting Telegram polling.")
        await dispatcher.start_polling(bot)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    await run_application(settings)


def run() -> None:
    """Synchronous entry point used by ``main.py`` and ``-m app``."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
