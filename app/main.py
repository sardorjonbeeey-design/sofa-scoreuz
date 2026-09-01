import asyncio
import logging
import os

from aiohttp import web

from app.bot.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.scheduler.scheduler import create_scheduler


async def health_check(request):
    return web.Response(text="Flash Football is running")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    port = int(os.getenv("PORT", "10000"))

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    return runner


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level.upper(),
            logging.INFO,
        ),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = create_bot(settings.bot_token)
    dispatcher = create_dispatcher(settings)
    scheduler = create_scheduler(settings)

    web_runner = await start_web_server()
    scheduler.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await web_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())