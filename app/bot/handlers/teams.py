import logging
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import (
    ACTION_ADD_TEAM,
    ACTION_REMOVE_TEAM,
    ACTION_VIEW_TEAM,
    is_legacy_add_callback,
    parse_team_callback,
    team_callback,
)
from app.bot.formatting import format_team_page, freshness_footer
from app.bot.handlers.common import edit_or_answer, user_language
from app.config import Settings
from app.football.errors import ProviderError
from app.football.models import Team
from app.football.service import FootballService
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import (
    ResolveStatus,
    TeamResolver,
    format_team_result,
)
from app.localization.i18n import text
from app.storage.database import StorageError
from app.storage.store import (
    AddFavoriteResult,
    FavoriteTeamRecord,
    PreferenceStore,
)

logger = logging.getLogger(__name__)

router = Router()

MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 60
REMOVE_BUTTON_NAME_LIMIT = 40

_RESOLVE_ERROR_KEYS = {
    ResolveStatus.QUOTA_EXCEEDED: "provider_quota",
    ResolveStatus.AUTH_ERROR: "provider_auth",
    ResolveStatus.UNAVAILABLE: "provider_unavailable",
}


class TeamSearchState(StatesGroup):
    waiting_for_name = State()


def teams_keyboard(teams, language: str):
    builder = InlineKeyboardBuilder()

    for team in teams:
        builder.button(
            text=format_team_result(team),
            callback_data=team_callback(ACTION_VIEW_TEAM, team.id),
        )

    builder.button(
        text=text("back", language),
        callback_data="menu:teams",
    )

    builder.adjust(1)

    return builder.as_markup()


def my_teams_keyboard(
    language: str,
    favorites: list[FavoriteTeamRecord] | None = None,
):
    rows: list[list[InlineKeyboardButton]] = []

    for favorite in favorites or []:
        name = favorite.team_name

        if len(name) > REMOVE_BUTTON_NAME_LIMIT:
            name = name[: REMOVE_BUTTON_NAME_LIMIT - 1] + "…"

        rows.append(
            [
                # Opens the team page (info and fixtures).
                InlineKeyboardButton(
                    text=f"⚽ {name}",
                    callback_data=team_callback(
                        ACTION_VIEW_TEAM,
                        favorite.team_id,
                    ),
                ),
                InlineKeyboardButton(
                    text="❌",
                    callback_data=team_callback(
                        ACTION_REMOVE_TEAM,
                        favorite.team_id,
                    ),
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=text("add_team", language),
                callback_data="team:search",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=text("back", language),
                callback_data="menu:main",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard(language: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=text("back", language),
        callback_data="menu:teams",
    )

    return builder.as_markup()


def favorites_message(
    language: str,
    favorites: list[FavoriteTeamRecord],
    notice: str | None = None,
) -> str:
    parts = [f"<b>{text('my_teams', language)}</b>"]

    if notice:
        parts.append(notice)

    if not favorites:
        parts.append(text("no_teams", language))
    else:
        parts.append(
            "\n".join(
                # Team names come from an external API: escape them,
                # because the bot sends messages as HTML.
                f"{index}. ⚽ {escape(team.team_name)}"
                for index, team in enumerate(favorites, start=1)
            )
        )
        parts.append(text("remove_team_hint", language))

    return "\n\n".join(parts)


async def _show_favorites(
    callback: CallbackQuery,
    store: PreferenceStore,
    language: str,
    notice: str | None = None,
) -> None:
    favorites = await store.list_favorites(callback.from_user.id)

    await edit_or_answer(
        callback,
        favorites_message(language, favorites, notice),
        my_teams_keyboard(language, favorites),
    )


@router.callback_query(F.data == "menu:teams")
async def show_my_teams(
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

    # Leaving the search prompt: stop treating text as a team name.
    await state.set_state(None)

    try:
        await _show_favorites(callback, store, language)
    except StorageError:
        await edit_or_answer(
            callback,
            text("storage_error", language),
            back_keyboard(language),
        )

    await callback.answer()


@router.callback_query(F.data == "team:search")
async def start_team_search(
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

    await state.set_state(
        TeamSearchState.waiting_for_name
    )

    # A way out, so the prompt is never a dead end.
    await edit_or_answer(
        callback,
        text("send_team_name", language),
        back_keyboard(language),
    )

    await callback.answer()


@router.message(TeamSearchState.waiting_for_name)
async def search_team(
    message: Message,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    resolver: TeamResolver | None,
    directory: TeamDirectory,
) -> None:

    language = await user_language(
        store,
        settings,
        message.from_user.id,
    )

    query = " ".join((message.text or "").split())

    if not query:
        await message.answer(
            text("send_team_name", language)
        )
        return

    if len(query) < MIN_QUERY_LENGTH:
        await message.answer(text("query_too_short", language))
        return

    if len(query) > MAX_QUERY_LENGTH:
        await message.answer(text("query_too_long", language))
        return

    if resolver is None:
        logger.error(
            "Team search requested but API_FOOTBALL_KEY is not "
            "configured."
        )
        await message.answer(
            text("provider_auth", language),
            reply_markup=back_keyboard(language),
        )
        return

    try:
        result = await resolver.resolve(query)
    except Exception:
        logger.exception("Unexpected failure during team search.")
        await message.answer(
            text("provider_unavailable", language),
            reply_markup=back_keyboard(language),
        )
        return

    error_key = _RESOLVE_ERROR_KEYS.get(result.status)

    if error_key is not None:
        await message.answer(
            text(error_key, language),
            reply_markup=back_keyboard(language),
        )
        return

    if not result.teams:
        await message.answer(
            text("no_teams_found", language)
        )
        await state.set_state(
            TeamSearchState.waiting_for_name
        )
        return

    # Buttons carry only team ids; remember the teams so the
    # selection can be resolved (and validated) when pressed.
    await directory.remember(result.teams)

    await message.answer(
        text("team_search_results", language),
        reply_markup=teams_keyboard(
            result.teams,
            language,
        ),
    )

    # Only leave the search state: language and favorites live in
    # the database and are unaffected.
    await state.set_state(None)


async def lookup_team(
    team_id: int,
    directory: TeamDirectory,
    service: FootballService | None,
) -> Team | None:
    """Find a team by id without trusting anything from the callback.

    Recent search results first (free); otherwise ask the provider
    (cached for a day). ``None`` means the team cannot be identified.
    """
    team = await directory.get(team_id)

    if team is not None or service is None:
        return team

    try:
        team = await service.provider.get_team(team_id)
    except ProviderError as exc:
        logger.warning(
            "Could not look up team %s (%s).",
            team_id,
            type(exc).__name__,
        )
        return None

    if team is not None:
        await directory.remember([team])

    return team


def team_page_keyboard(
    language: str,
    team_id: int,
    is_favorite: bool,
) -> InlineKeyboardMarkup:
    if is_favorite:
        toggle = InlineKeyboardButton(
            text=text("remove_from_favorites", language),
            callback_data=team_callback(ACTION_REMOVE_TEAM, team_id),
        )
    else:
        toggle = InlineKeyboardButton(
            text=text("add_to_favorites", language),
            callback_data=team_callback(ACTION_ADD_TEAM, team_id),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle],
            [
                InlineKeyboardButton(
                    text=text("back", language),
                    callback_data="menu:teams",
                )
            ],
        ]
    )


@router.callback_query(F.data.startswith("team:view:"))
async def view_team(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    directory: TeamDirectory,
    service: FootballService | None = None,
) -> None:
    """Team page: details, next matches, last results, favorite toggle."""
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    team_id = parse_team_callback(callback.data, ACTION_VIEW_TEAM)

    if team_id is None:
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    await state.set_state(None)

    try:
        favorites = await store.list_favorites(callback.from_user.id)
    except StorageError:
        await callback.answer(
            text("storage_error", language),
            show_alert=True,
        )
        return

    saved = next((f for f in favorites if f.team_id == team_id), None)
    team = await lookup_team(team_id, directory, service)

    if team is None and saved is not None:
        # Provider unreachable, but the user saved this team earlier.
        team = Team(id=saved.team_id, name=saved.team_name)

    if team is None:
        await callback.answer(
            text("search_expired", language),
            show_alert=True,
        )
        return

    matches = None
    footer = ""

    if service is not None:
        try:
            snapshot = await service.team_matches(team_id)
        except ProviderError as exc:
            logger.warning(
                "Fixtures for team %s unavailable (%s).",
                team_id,
                type(exc).__name__,
            )
        else:
            matches = snapshot.value
            footer = "\n\n" + freshness_footer(
                snapshot.fetched_at,
                snapshot.stale,
                language=language,
                tz=service.tz,
                tz_name=service.timezone_name,
            )

    tz = service.tz if service is not None else None

    if tz is None:
        from datetime import timezone as _utc

        tz = _utc.utc

    await edit_or_answer(
        callback,
        format_team_page(team, language, tz, matches) + footer,
        team_page_keyboard(language, team_id, saved is not None),
    )

    await callback.answer()


@router.callback_query(F.data.startswith("team:add:"))
async def add_team(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    directory: TeamDirectory,
    service: FootballService | None = None,
) -> None:

    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    team_id = parse_team_callback(callback.data, ACTION_ADD_TEAM)

    if team_id is None:
        key = (
            "search_expired"
            if is_legacy_add_callback(callback.data)
            else "invalid_action"
        )
        await callback.answer(text(key, language), show_alert=True)
        return

    team = await lookup_team(team_id, directory, service)

    if team is None:
        await callback.answer(
            text("search_expired", language),
            show_alert=True,
        )
        return

    limit = settings.free_favorite_slots

    try:
        outcome = await store.add_favorite(
            callback.from_user.id,
            team.id,
            team.name,
            limit,
        )
    except StorageError:
        await callback.answer(
            text("storage_error", language),
            show_alert=True,
        )
        return

    if outcome is AddFavoriteResult.DUPLICATE:
        await callback.answer(
            text("team_already_added", language),
            show_alert=True,
        )
        return

    if outcome is AddFavoriteResult.LIMIT_REACHED:
        await callback.answer(
            text("team_limit", language, limit=limit),
            show_alert=True,
        )
        return

    try:
        await _show_favorites(
            callback,
            store,
            language,
            notice=text("team_added", language),
        )
    except StorageError:
        # The team WAS saved; only refreshing the list failed.
        await callback.answer(
            text("team_added", language),
            show_alert=True,
        )
        return

    await callback.answer()


@router.callback_query(F.data.startswith("team:rm:"))
async def remove_team(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
) -> None:

    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    team_id = parse_team_callback(callback.data, ACTION_REMOVE_TEAM)

    if team_id is None:
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    try:
        removed = await store.remove_favorite(
            callback.from_user.id,
            team_id,
        )
        notice = text(
            "team_removed" if removed else "team_not_in_favorites",
            language,
        )
        await _show_favorites(
            callback,
            store,
            language,
            notice=notice,
        )
    except StorageError:
        await callback.answer(
            text("storage_error", language),
            show_alert=True,
        )
        return

    await callback.answer()
