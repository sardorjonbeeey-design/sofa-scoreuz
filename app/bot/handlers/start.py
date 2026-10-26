import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.handlers.common import edit_or_answer, user_language
from app.bot.handlers.menu import back_to_menu_keyboard, main_menu
from app.config import Settings
from app.football.service import FootballService
from app.localization.i18n import SUPPORTED_LANGUAGES, text
from app.storage.database import StorageError
from app.storage.store import PreferenceStore

logger = logging.getLogger(__name__)

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
    # Only the transient FSM state is cleared. The user's saved
    # language and favorites are stored in the database and are kept.
    await state.clear()

    await message.answer(
        text("choose_language"),
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def language_handler(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
) -> None:
    language = (callback.data or "").partition(":")[2]

    if language not in SUPPORTED_LANGUAGES:
        current = await user_language(
            store,
            settings,
            callback.from_user.id,
        )
        await callback.answer(
            text("invalid_action", current),
            show_alert=True,
        )
        return

    try:
        await store.set_language(callback.from_user.id, language)
    except StorageError:
        # Not saved, so do not switch the interface as if it were.
        current = await user_language(
            store,
            settings,
            callback.from_user.id,
        )
        await callback.answer(
            text("storage_error", current),
            show_alert=True,
        )
        return

    await callback.answer(
        text("language_saved", language)
    )

    await edit_or_answer(
        callback,
        text("welcome", language),
        main_menu(language),
    )


@router.callback_query(F.data == "menu:settings")
async def settings_handler(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await state.set_state(None)

    timezone = service.timezone_name if service else settings.display_timezone
    keyboard = language_keyboard()
    keyboard.inline_keyboard.extend(
        back_to_menu_keyboard(language).inline_keyboard
    )

    await edit_or_answer(
        callback,
        text("settings_title", language)
        + "\n\n"
        + text("settings_timezone", language, tz=timezone),
        keyboard,
    )

    await callback.answer()
