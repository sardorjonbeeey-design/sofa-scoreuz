from aiogram import Router
from aiogram.types import CallbackQuery

from app.localization.i18n import text

router = Router()


@router.callback_query(lambda callback: callback.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery) -> None:
    language = "uz"

    section = callback.data.split(":")[1]

    if section == "teams":
        message = text("coming_soon", language)
    elif section == "matches":
        message = text("coming_soon", language)
    elif section == "news":
        message = text("coming_soon", language)
    elif section == "standings":
        message = text("coming_soon", language)
    elif section == "settings":
        message = text("coming_soon", language)
    else:
        message = text("coming_soon", language)

    await callback.answer()
    await callback.message.answer(message)