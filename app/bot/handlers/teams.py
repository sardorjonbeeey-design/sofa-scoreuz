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
    parse_team_feature_callback,
    team_callback,
)
from app.bot.formatting import (
    format_team_page,
    format_team_upcoming,
    freshness_footer,
)
from app.bot.handlers.common import edit_or_answer, user_language
from app.config import Settings
from app.football.errors import ProviderError
from app.football.models import Team
from app.football.news import football_news
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
    saved = favorites or []

    for favorite in saved:
        name = favorite.team_name

        if len(name) > REMOVE_BUTTON_NAME_LIMIT:
            name = name[: REMOVE_BUTTON_NAME_LIMIT - 1] + "…"

        slot_label = text(
            "national_team_slot" if favorite.team_type == "national" else "club_slot",
            language,
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{slot_label}: {name}",
                    callback_data=team_callback(ACTION_VIEW_TEAM, favorite.team_id),
                ),
                InlineKeyboardButton(
                    text="❌",
                    callback_data=team_callback(ACTION_REMOVE_TEAM, favorite.team_id),
                ),
            ]
        )

    if not any(item.team_type == "club" for item in saved):
        rows.append([InlineKeyboardButton(
            text=text("add_club", language),
            callback_data="team:search:club",
        )])

    if not any(item.team_type == "national" for item in saved):
        rows.append([InlineKeyboardButton(
            text=text("add_national_team", language),
            callback_data="team:search:national",
        )])

    rows.append([
        InlineKeyboardButton(
            text=text("back", language),
            callback_data="menu:main",
        )
    ])

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
                (
                    f"{text('national_team_slot' if team.team_type == 'national' else 'club_slot', language)}: "
                    f"{escape(team.team_name)}"
                )
                for team in favorites
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


@router.callback_query(F.data.in_({"team:search", "team:search:club", "team:search:national"}))
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

    if callback.data == "team:search:national":
        team_type = "national"
    elif callback.data == "team:search:club":
        team_type = "club"
    else:
        team_type = "all"
    await state.set_state(TeamSearchState.waiting_for_name)
    await state.update_data(team_type=team_type)

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
    state_data = await state.get_data()
    requested_type = state_data.get("team_type", "club")

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

    matching_teams = [
        team for team in result.teams
        if requested_type == "all"
        or team.national == (requested_type == "national")
    ]

    if not matching_teams:
        await message.answer(text("no_teams_found", language))
        await state.set_state(TeamSearchState.waiting_for_name)
        return

    # Only results of the selected slot type can be added.
    await directory.remember(matching_teams)

    await message.answer(
        text("team_search_results", language),
        reply_markup=teams_keyboard(matching_teams, language),
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
                    text=text("team_squad", language),
                    callback_data=f"team:squad:{team_id}",
                ),
                InlineKeyboardButton(
                    text=text("team_news", language),
                    callback_data=f"team:news:{team_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=text("team_next_games", language),
                    callback_data=f"team:games:{team_id}",
                ),
                InlineKeyboardButton(
                    text=text("team_standings", language),
                    callback_data="menu:standings",
                ),
            ],
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
        team = Team(
            id=saved.team_id,
            name=saved.team_name,
            national=saved.team_type == "national",
        )

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




def _team_subpage_keyboard(language: str, team_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=text("back", language),
                callback_data=team_callback(ACTION_VIEW_TEAM, team_id),
            )
        ]]
    )


@router.callback_query(F.data.startswith("team:squad:"))
async def team_squad_page(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    directory: TeamDirectory,
    service: FootballService | None = None,
) -> None:
    language = await user_language(store, settings, callback.from_user.id)
    team_id = parse_team_feature_callback(callback.data, "squad")
    if team_id is None:
        await callback.answer(text("invalid_action", language), show_alert=True)
        return

    team = await lookup_team(team_id, directory, service)
    if team is None:
        await callback.answer(text("search_expired", language), show_alert=True)
        return

    if service is None:
        body = f"<b>{escape(team.name)} — {text('squad_title', language)}</b>\n\n{text('squad_unavailable', language)}"
    else:
        try:
            snapshot = await service.team_squad(team_id)
        except ProviderError as exc:
            logger.warning("Squad for team %s unavailable (%s).", team_id, type(exc).__name__)
            body = f"<b>{escape(team.name)} — {text('squad_title', language)}</b>\n\n{text('squad_unavailable', language)}"
        else:
            lines = [f"👥 <b>{escape(team.name)} — {text('squad_title', language)}</b>"]
            if not snapshot.value:
                lines.append(text("no_squad", language))
            else:
                for player in snapshot.value[:35]:
                    number = f"{player.number}. " if player.number is not None else ""
                    position = f" — {escape(player.position)}" if player.position else ""
                    age = f" ({player.age})" if player.age is not None else ""
                    lines.append(f"{number}{escape(player.name)}{age}{position}")
                lines.append("")
                lines.append(freshness_footer(
                    snapshot.fetched_at,
                    snapshot.stale,
                    language=language,
                    tz=service.tz,
                    tz_name=service.timezone_name,
                ))
            body = "\n".join(lines)

    await edit_or_answer(callback, body, _team_subpage_keyboard(language, team_id))
    await callback.answer()


@router.callback_query(F.data.startswith("team:news:"))
async def team_news_page(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    directory: TeamDirectory,
    service: FootballService | None = None,
) -> None:
    language = await user_language(store, settings, callback.from_user.id)
    team_id = parse_team_feature_callback(callback.data, "news")
    if team_id is None:
        await callback.answer(text("invalid_action", language), show_alert=True)
        return

    team = await lookup_team(team_id, directory, service)
    if team is None:
        await callback.answer(text("search_expired", language), show_alert=True)
        return

    await callback.answer()
    try:
        items = await football_news(team_name=team.name, language=language, limit=5)
    except Exception:
        logger.exception("Could not load news for team %s.", team_id)
        items = ()

    if items:
        label = text("team_news", language).replace("📰 ", "")
        lines = [f"📰 <b>{escape(team.name)} — {escape(label)}</b>"]
        for index, item in enumerate(items, start=1):
            title = escape(item.title)
            url = escape(item.url, quote=True)
            source = f" <i>— {escape(item.source)}</i>" if item.source else ""
            lines.append(f'{index}. <a href="{url}">{title}</a>{source}')
        body = "\n\n".join(lines)
    else:
        body = f"<b>{escape(team.name)}</b>\n\n{text('no_news', language)}"

    await edit_or_answer(callback, body, _team_subpage_keyboard(language, team_id))


@router.callback_query(F.data.startswith("team:games:"))
async def team_games_page(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    directory: TeamDirectory,
    service: FootballService | None = None,
) -> None:
    language = await user_language(store, settings, callback.from_user.id)
    team_id = parse_team_feature_callback(callback.data, "games")
    if team_id is None:
        await callback.answer(text("invalid_action", language), show_alert=True)
        return

    team = await lookup_team(team_id, directory, service)
    if team is None:
        await callback.answer(text("search_expired", language), show_alert=True)
        return

    matches = None
    footer = ""
    if service is not None:
        try:
            snapshot = await service.team_matches(team_id)
            matches = snapshot.value
            footer = freshness_footer(
                snapshot.fetched_at,
                snapshot.stale,
                language=language,
                tz=service.tz,
                tz_name=service.timezone_name,
            )
        except ProviderError as exc:
            logger.warning("Upcoming games for team %s unavailable (%s).", team_id, type(exc).__name__)

    from datetime import timezone
    body = format_team_upcoming(
        team, language, service.tz if service else timezone.utc, matches
    )
    if footer:
        body += "\n\n" + footer
    await edit_or_answer(callback, body, _team_subpage_keyboard(language, team_id))
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
        team_type = "national" if team.national else "club"
        outcome = await store.add_favorite(
            callback.from_user.id,
            team.id,
            team.name,
            limit,
            team_type=team_type,
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
        key = "national_slot_full" if team.national else "club_slot_full"
        await callback.answer(text(key, language), show_alert=True)
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
