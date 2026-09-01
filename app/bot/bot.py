from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import Settings
from app.bot.handlers.start import router


def create_bot(token: str) -> Bot:
    if not token:
        raise ValueError("BOT_TOKEN is not configured.")

    return Bot(
        token=token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher()

    dispatcher.include_router(router)

    return dispatcher