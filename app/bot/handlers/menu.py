from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.localization.i18n import text

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
) -> None:
    data = await state.get_data()
    language = data.get("language", "uz")

    await callback.message.edit_text(
        text("welcome", language),
        reply_markup=main_menu(language),
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
    state: FSMContext,
) -> None:
    data = await state.get_data()
    language = data.get("language", "uz")

    await callback.answer()

    await callback.message.answer(
        text("coming_soon", language)
    )