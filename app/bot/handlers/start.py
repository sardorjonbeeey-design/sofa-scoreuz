from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.localization.i18n import text

router = Router()


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇺🇿 O‘zbekcha",
                    callback_data="lang:uz",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data="lang:ru",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="lang:en",
                ),
            ],
        ]
    )


def main_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text("my_teams", language),
                    callback_data="menu:teams",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=text("matches", language),
                    callback_data="menu:matches",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=text("news", language),
                    callback_data="menu:news",
                ),
                InlineKeyboardButton(
                    text=text("standings", language),
                    callback_data="menu:standings",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=text("settings", language),
                    callback_data="menu:settings",
                ),
            ],
        ]
    )


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        text("choose_language"),
        reply_markup=language_keyboard(),
    )


@router.callback_query(lambda callback: callback.data.startswith("lang:"))
async def language_handler(callback: CallbackQuery) -> None:
    language = callback.data.split(":")[1]

    await callback.answer(text("language_saved", language))

    await callback.message.edit_text(
        text("welcome", language),
        reply_markup=main_menu(language),
    )