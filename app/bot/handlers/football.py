"""Live scores, today's matches, leagues and standings."""

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot.callbacks import (
    KIND_LIVE,
    KIND_TODAY,
    SCOPE_TOP,
    country_callback,
    fixtures_callback,
    league_callback,
    parse_country_callback,
    parse_fixtures_callback,
    parse_league_callback,
)
from app.bot.formatting import (
    build_match_pages,
    filter_scope,
    format_standings,
    freshness_footer,
)
from app.bot.handlers.common import (
    edit_or_answer,
    favorite_team_ids,
    provider_error_key,
    user_language,
)
from app.config import Settings
from app.football.errors import ProviderError
from app.football.leagues import (
    FEATURED_COUNTRIES,
    FEATURED_LEAGUES,
    country_by_code,
    featured_league,
)
from app.football.service import FootballService
from app.localization.i18n import text
from app.storage.store import PreferenceStore

logger = logging.getLogger(__name__)

router = Router()


def _button(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=data)


def _markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def _back_row(language: str, target: str = "menu:main"):
    return [_button(text("back", language), target)]


async def _show_error(
    callback: CallbackQuery,
    language: str,
    key: str,
    *,
    retry: str | None = None,
    back: str = "menu:main",
) -> None:
    rows = []

    if retry:
        rows.append([_button(text("refresh", language), retry)])

    rows.append(_back_row(language, back))

    await edit_or_answer(callback, text(key, language), _markup(*rows))
    await callback.answer()


# --- live scores and today's matches -----------------------------------


@router.callback_query(F.data == "menu:live")
async def live_entry(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    await _show_fixtures(
        callback, state, store, settings, service,
        KIND_LIVE, SCOPE_TOP, 0,
    )


@router.callback_query(F.data.in_({"menu:today", "menu:matches"}))
async def today_entry(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    # "menu:matches" is the id older menus used for this screen.
    await _show_fixtures(
        callback, state, store, settings, service,
        KIND_TODAY, SCOPE_TOP, 0,
    )


@router.callback_query(F.data.startswith("fx:"))
async def fixtures_page(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    parsed = parse_fixtures_callback(callback.data)

    if parsed is None:
        language = await user_language(
            store, settings, callback.from_user.id
        )
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    kind, scope, page = parsed

    await _show_fixtures(
        callback, state, store, settings, service, kind, scope, page,
    )


async def _show_fixtures(
    callback: CallbackQuery,
    state: FSMContext,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None,
    kind: str,
    scope: str,
    page: int,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    await state.set_state(None)

    here = fixtures_callback(kind, scope, page)

    if service is None:
        # No API key configured: say the service is unavailable.
        await _show_error(callback, language, "provider_auth")
        return

    try:
        if kind == KIND_LIVE:
            snapshot = await service.live_fixtures()
        else:
            snapshot = await service.todays_fixtures()
    except ProviderError as exc:
        logger.warning(
            "Fixtures (%s) unavailable: %s",
            kind,
            type(exc).__name__,
        )
        await _show_error(
            callback,
            language,
            provider_error_key(exc),
            retry=here,
        )
        return

    favorites = await favorite_team_ids(store, callback.from_user.id)
    fixtures = snapshot.value
    # Live and today's matches always use the same fixed competition scope.
    # The scope value is retained only for older callback payloads.
    shown = filter_scope(fixtures, True, favorites)
    pages = build_match_pages(
        shown,
        language=language,
        tz=service.tz,
        favorite_ids=favorites,
    )

    if kind == KIND_LIVE:
        title = text("live_title", language)
    else:
        title = text(
            "today_title",
            language,
            date=service.today().strftime("%d.%m.%Y"),
        )

    if not pages:
        if fixtures:
            body = text("no_top_matches", language, count=len(fixtures))
        else:
            body = text(
                "no_live" if kind == KIND_LIVE else "no_today",
                language,
            )

        page = 0
    else:
        page = min(page, len(pages) - 1)
        body = pages[page]

    parts = [title, body]

    if len(pages) > 1:
        parts.append(f"📄 {page + 1}/{len(pages)}")

    parts.append(
        freshness_footer(
            snapshot.fetched_at,
            snapshot.stale,
            language=language,
            tz=service.tz,
            tz_name=service.timezone_name,
        )
    )

    navigation = []

    if page > 0:
        navigation.append(
            _button("◀️", fixtures_callback(kind, scope, page - 1))
        )

    if page + 1 < len(pages):
        navigation.append(
            _button("▶️", fixtures_callback(kind, scope, page + 1))
        )

    rows = []

    if navigation:
        rows.append(navigation)

    rows.append([
        _button(
            text("refresh", language),
            fixtures_callback(kind, SCOPE_TOP, page),
        )
    ])
    rows.append(_back_row(language))

    await edit_or_answer(
        callback,
        "\n\n".join(parts),
        _markup(*rows),
    )
    await callback.answer()


# --- leagues and standings ---------------------------------------------


@router.callback_query(F.data == "menu:standings")
async def leagues_menu(
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

    rows = [
        [_button(f"{league.flag} {league.name}", league_callback(league.id))]
        for league in FEATURED_LEAGUES
    ]
    rows.extend(
        [
            _button(
                f"{country.flag} {country.name}",
                country_callback(country.code),
            )
        ]
        for country in FEATURED_COUNTRIES
    )
    rows.append(_back_row(language))

    await edit_or_answer(
        callback,
        text("standings_pick", language),
        _markup(*rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lgc:"))
async def country_leagues(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    code = parse_country_callback(callback.data)
    country = country_by_code(code) if code else None

    if country is None:
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    if service is None:
        await _show_error(
            callback, language, "provider_auth", back="menu:standings"
        )
        return

    try:
        snapshot = await service.country_leagues(country.name)
    except ProviderError as exc:
        logger.warning(
            "Leagues of %s unavailable: %s",
            country.name,
            type(exc).__name__,
        )
        await _show_error(
            callback,
            language,
            provider_error_key(exc),
            retry=country_callback(country.code),
            back="menu:standings",
        )
        return

    rows = [
        [_button(league.name, league_callback(league.id))]
        for league in snapshot.value
    ]
    rows.append(_back_row(language, "menu:standings"))

    if snapshot.value:
        body = text(
            "country_leagues_title",
            language,
            flag=country.flag,
            country=country.name,
        )
    else:
        body = text("no_country_leagues", language)

    await edit_or_answer(callback, body, _markup(*rows))
    await callback.answer()


@router.callback_query(F.data.startswith("lg:"))
async def league_table(
    callback: CallbackQuery,
    store: PreferenceStore,
    settings: Settings,
    service: FootballService | None = None,
) -> None:
    language = await user_language(
        store,
        settings,
        callback.from_user.id,
    )

    league_id = parse_league_callback(callback.data)

    if league_id is None:
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    if service is None:
        await _show_error(
            callback, language, "provider_auth", back="menu:standings"
        )
        return

    # Only leagues the bot itself offered may be requested, so a forged
    # callback cannot spend API quota on arbitrary ids.
    if not await service.is_known_league(league_id):
        await callback.answer(
            text("invalid_action", language),
            show_alert=True,
        )
        return

    # Standings now come from the TinyFish archive only. Do not call
    # API-Football here: its account may be suspended, and each refresh should
    # reuse the shared archive instead of spending provider quota.
    fallback = await service.tinyfish_standings_search(league_id)
    if fallback is not None:
        table = fallback.get("table")
        if isinstance(table, dict) and table.get("verified_structure") and isinstance(table.get("rows"), list):
            body = _format_tinyfish_standings_table(fallback, language)
        else:
            body = _format_tinyfish_standings_search(fallback, language)
        await edit_or_answer(
            callback,
            body,
            _markup(
                [_button(text("refresh", language), league_callback(league_id))],
                _back_row(language, "menu:standings"),
            ),
        )
        await callback.answer()
        return

    if language == "uz":
        unavailable = "TinyFish hali bu liga uchun jadvalni arxivlamadi. Birozdan keyin qayta urinib ko‘ring."
    elif language == "ru":
        unavailable = "TinyFish ещё не сохранил таблицу этой лиги. Попробуйте позже."
    else:
        unavailable = "TinyFish has not archived standings for this league yet. Please try again later."
    await edit_or_answer(
        callback,
        unavailable,
        _markup(
            [_button(text("refresh", language), league_callback(league_id))],
            _back_row(language, "menu:standings"),
        ),
    )
    await callback.answer()
    return

def _warn_if_unexpected_league(league_id: int, league) -> None:
    """Log when a catalog id does not return the competition we expect."""
    expected = featured_league(league_id)

    if expected is None or league is None:
        return

    ours, theirs = expected.name.lower(), league.name.lower()

    if ours not in theirs and theirs not in ours:
        logger.warning(
            "League id %s is listed as %r but the provider says %r; "
            "check app/football/leagues.py.",
            league_id,
            expected.name,
            league.name,
        )
