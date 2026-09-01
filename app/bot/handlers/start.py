from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.localization.i18n import text

router = Router()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ My Teams",
                    callback_data="menu:teams",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Upcoming Matches",
                    callback_data="menu:matches",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📰 News",
                    callback_data="menu:news",
                ),
                InlineKeyboardButton(
                    text="📊 Standings",
                    callback_data="menu:standings",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Settings",
                    callback_data="menu:settings",
                ),
            ],
        ]
    )


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        text("welcome", "uz"),
        reply_markup=main_menu(),
    )