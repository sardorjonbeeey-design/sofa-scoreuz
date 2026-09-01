from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.localization.i18n import text
from app.bot.handlers.menu import main_menu

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


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        text("choose_language"),
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def language_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    language = callback.data.split(":")[1]

    await state.update_data(
        language=language,
        favorite_teams=[],
    )

    await callback.answer(
        text("language_saved", language)
    )

    await callback.message.edit_text(
        text("welcome", language),
        reply_markup=main_menu(language),
    )