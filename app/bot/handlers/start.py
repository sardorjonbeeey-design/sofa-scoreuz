from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.localization.i18n import text

router = Router()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(text("welcome", "uz"))