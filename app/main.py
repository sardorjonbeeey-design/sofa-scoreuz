import asyncio
import logging

from app.bot.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.scheduler.scheduler import create_scheduler


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

    scheduler.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())