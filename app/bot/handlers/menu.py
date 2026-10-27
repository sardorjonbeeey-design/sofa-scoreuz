import logging
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot.handlers.common import edit_or_answer, user_language
from app.config import Settings
from app.football.news import football_news
from app.localization.i18n import text
from app.storage.store import PreferenceStore

router = Router()
logger = logging.getLogger(__name__)


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
                _button(text("news", language), "menu:news"),
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
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await state.set_state(None)
    await callback.answer()

    try:
        items = await football_news(language=language)
    except Exception:
        logger.exception("Could not load football news.")
        items = ()

    if items:
        lines = [text("news_title", language)]
        for index, item in enumerate(items, start=1):
            title = escape(item.title)
            url = escape(item.url, quote=True)
            source = f" <i>— {escape(item.source)}</i>" if item.source else ""
            lines.append(f'{index}. <a href="{url}">{title}</a>{source}')
        body = "\n\n".join(lines)
    else:
        body = text("news_unavailable", language)

    await edit_or_answer(
        callback,
        body,
        back_to_menu_keyboard(language),
    )
