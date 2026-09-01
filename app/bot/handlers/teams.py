from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import get_settings
from app.football.api_football import ApiFootballProvider
from app.localization.i18n import text


router = Router()


class TeamSearchState(StatesGroup):
    waiting_for_name = State()


def get_language(data: dict) -> str:
    return data.get("language", "uz")


def teams_keyboard(teams, language: str):
    builder = InlineKeyboardBuilder()

    for team in teams:
        builder.button(
            text=team.name,
            callback_data=f"team:add:{team.id}:{team.name[:30]}",
        )

    builder.button(
        text=text("back", language),
        callback_data="menu:teams",
    )

    builder.adjust(1)

    return builder.as_markup()


def my_teams_keyboard(language: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=text("add_team", language),
        callback_data="team:search",
    )

    builder.button(
        text=text("back", language),
        callback_data="menu:main",
    )

    builder.adjust(1)

    return builder.as_markup()


@router.callback_query(F.data == "menu:teams")
async def show_my_teams(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    data = await state.get_data()
    language = get_language(data)

    teams = data.get("favorite_teams", [])

    if not teams:
        message_text = text("no_teams", language)
    else:
        team_lines = [
            f"{index}. ⚽ {team['name']}"
            for index, team in enumerate(teams, start=1)
        ]

        message_text = "\n".join(team_lines)

    await callback.message.edit_text(
        message_text,
        reply_markup=my_teams_keyboard(language),
    )

    await callback.answer()


@router.callback_query(F.data == "team:search")
async def start_team_search(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    data = await state.get_data()
    language = get_language(data)

    await state.set_state(TeamSearchState.waiting_for_name)

    await callback.message.edit_text(
        text("send_team_name", language)
    )

    await callback.answer()


@router.message(TeamSearchState.waiting_for_name)
async def search_team(
    message: Message,
    state: FSMContext,
) -> None:

    data = await state.get_data()
    language = get_language(data)

    query = (message.text or "").strip()

    if not query:
        await message.answer(
            text("send_team_name", language)
        )
        return

    settings = get_settings()

    provider = ApiFootballProvider(
        settings.api_football_key
    )

    try:
        teams = await provider.search_teams(query)
    finally:
        await provider.close()

    if not teams:
        await message.answer(
            text("no_teams_found", language)
        )
        return

    await message.answer(
        text("team_search_results", language),
        reply_markup=teams_keyboard(
            teams[:10],
            language,
        ),
    )

    await state.set_state(None)


@router.callback_query(F.data.startswith("team:add:"))
async def add_team(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    data = await state.get_data()
    language = get_language(data)

    parts = callback.data.split(":", 3)

    team_id = int(parts[2])
    team_name = parts[3]

    favorite_teams = data.get(
        "favorite_teams",
        [],
    )

    if any(
        team["id"] == team_id
        for team in favorite_teams
    ):
        await callback.answer(
            text("team_already_added", language),
            show_alert=True,
        )
        return

    if len(favorite_teams) >= 3:
        await callback.answer(
            text("team_limit", language),
            show_alert=True,
        )
        return

    favorite_teams.append(
        {
            "id": team_id,
            "name": team_name,
        }
    )

    await state.update_data(
        favorite_teams=favorite_teams
    )

    await callback.message.edit_text(
        text("team_added", language),
        reply_markup=my_teams_keyboard(language),
    )

    await callback.answer()