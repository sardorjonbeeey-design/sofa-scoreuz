from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Settings
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.start import router as start_router


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
    dispatcher = Dispatcher(
        storage=MemoryStorage()
    )

    dispatcher.include_router(start_router)
    dispatcher.include_router(menu_router)

    return dispatcher