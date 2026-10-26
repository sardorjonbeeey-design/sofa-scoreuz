from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot.handlers.common import edit_or_answer, user_language
from app.config import Settings
from app.localization.i18n import text
from app.storage.store import PreferenceStore

router = Router()

# Marks a menu entry whose feature does not exist yet.
UNFINISHED_MARK = "🚧"


def _button(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=data)


def main_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(text("my_teams", language), "menu:teams")],
            [
                _button(text("live", language), "menu:live"),
                _button(text("today", language), "menu:today"),
            ],
            [
                _button(text("standings", language), "menu:standings"),
                _button(text("find_team", language), "team:search"),
            ],
            [
                # News has no data source yet: say so on the button.
                _button(
                    f"{text('news', language)} {UNFINISHED_MARK}",
                    "menu:news",
                ),
                _button(text("settings", language), "menu:settings"),
            ],
        ]
    )


def back_to_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(text("back", language), "menu:main")],
        ]
    )


@router.callback_query(F.data == "menu:main")
async def main_menu_handler(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await state.set_state(None)

    await edit_or_answer(
        callback,
        text("welcome", language),
        main_menu(language),
    )

    await callback.answer()


@router.callback_query(F.data == "menu:news")
async def news_handler(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
) -> None:
    """News is NOT implemented (no news source is connected).

    The screen says so plainly instead of pretending to be a feature.
    """
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await state.set_state(None)

    await edit_or_answer(
        callback,
        text("news_unavailable", language),
        back_to_menu_keyboard(language),
    )

    await callback.answer()
