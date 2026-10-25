from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.handlers.common import edit_or_answer, user_language
from app.config import Settings
from app.localization.i18n import text
from app.storage.store import PreferenceStore

router = Router()


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


@router.callback_query(F.data.in_({
    "menu:matches",
    "menu:news",
    "menu:standings",
    "menu:settings",
}))
async def coming_soon_handler(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await callback.answer()

    answer = getattr(callback.message, "answer", None)

    if answer is not None:
        await answer(text("coming_soon", language))
