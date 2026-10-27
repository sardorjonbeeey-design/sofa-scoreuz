"""Live scores, today's matches, leagues and standings."""

import html
import logging
import re

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


def _format_tinyfish_standings_table(payload: dict, language: str) -> str:
    """Render extracted standings; use a compact code/points view for the EPL."""
    league = html.escape(str(payload.get("league_name") or "League"))
    table = payload.get("table")
    if not isinstance(table, dict):
        return _format_tinyfish_standings_search(payload, language)
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        return _format_tinyfish_standings_search(payload, language)

    # Keep full team names in the archive. Abbreviations are presentation-only.
    is_premier_league = (
        table.get("league_id") == 39
        or str(payload.get("league_name") or "").strip().casefold() == "premier league"
    )
    if is_premier_league:
        team_codes = {
            "arsenal": "ARS",
            "aston villa": "AVL",
            "bournemouth": "BOU",
            "afc bournemouth": "BOU",
            "brentford": "BRE",
            "brentford fc": "BRE",
            "brighton": "BRI",
            "brighton & hove albion": "BRI",
            "chelsea": "CHE",
            "chelsea fc": "CHE",
            "crystal palace": "CRY",
            "everton": "EVE",
            "everton fc": "EVE",
            "fulham": "FUL",
            "fulham fc": "FUL",
            "liverpool": "LIV",
            "liverpool fc": "LIV",
            "manchester city": "MCI",
            "manchester city fc": "MCI",
            "manchester united": "MUN",
            "manchester united fc": "MUN",
            "newcastle united": "NEW",
            "nottingham forest": "NFO",
            "tottenham hotspur": "TOT",
            "west ham united": "WHU",
            "wolverhampton wanderers": "WOL",
            "wolves": "WOL",
        }
        lines = [f"🏆 <b>Premier League</b>", "", "<code>#  CLUB  PTS</code>"]
        for index, row in enumerate(rows[:30], start=1):
            if not isinstance(row, dict):
                continue
            raw_team = str(row.get("team") or "Unknown").strip()
            # Some sources repeat the rank in the team cell (e.g. "1 Arsenal").
            raw_team = re.sub(r"^\d+\s*[.)]?\s+", "", raw_team)
            code = team_codes.get(raw_team.casefold(), raw_team[:3].upper())
            position = row.get("position", index)
            points = row.get("points", "?")
            lines.append(f"{html.escape(str(position)):>2}.  <b>{html.escape(code)}</b>    {html.escape(str(points))}")
        source_url = table.get("source_url")
        if isinstance(source_url, str) and source_url.startswith("https://"):
            lines.extend(["", f'<a href="{html.escape(source_url, quote=True)}">Source</a>'])
        return "\\n".join(lines)[:3900]

    retrieved = html.escape(str(table.get("retrieved_at") or payload.get("queried_at") or "unknown"))
    season = table.get("season")
    if language == "uz":
        lines = [f"🏆 <b>{league} — turnir jadvali</b>", f"Yangilangan (UTC): {retrieved}"]
        labels = ("O", "G", "D", "M", "TF", "TO", "TF", "Ochko")
        footer = "Manba"
    elif language == "ru":
        lines = [f"🏆 <b>{league} — турнирная таблица</b>", f"Обновлено (UTC): {retrieved}"]
        labels = ("И", "В", "Н", "П", "ЗМ", "ЗП", "РМ", "Очки")
        footer = "Источник"
    else:
        lines = [f"🏆 <b>{league} — standings</b>", f"Retrieved (UTC): {retrieved}"]
        labels = ("P", "W", "D", "L", "GF", "GA", "GD", "Pts")
        footer = "Source"

    if season is not None:
        season_label = {"uz": "Mavsum", "ru": "Сезон"}.get(language, "Season")
        lines.append(f"{season_label} {html.escape(str(season))}")

    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        team = html.escape(str(row.get("team") or "Unknown")[:80])
        pos = row.get("position", "?")
        played = row.get("played", "?")
        points = row.get("points", "?")
        won, drawn, lost = row.get("won", "?"), row.get("drawn", "?"), row.get("lost", "?")
        gd = row.get("goal_difference", "?")
        gd_text = f"+{gd}" if isinstance(gd, int) and gd > 0 else str(gd)
        lines.append(f"{html.escape(str(pos))}. <b>{team}</b> — {labels[0]} {html.escape(str(played))}, "
                     f"{labels[1]} {html.escape(str(won))}, {labels[2]} {html.escape(str(drawn))}, "
                     f"{labels[3]} {html.escape(str(lost))}, GD {html.escape(gd_text)}, "
                     f"{labels[7]} {html.escape(str(points))}")

    source_url = table.get("source_url")
    source_title = html.escape(str(table.get("source_title") or footer)[:120])
    if isinstance(source_url, str) and source_url.startswith("https://"):
        lines.append(f'{footer}: <a href="{html.escape(source_url, quote=True)}">{source_title}</a>')
    else:
        lines.append(f"{footer}: {source_title}")
    return "\n".join(lines)[:3900]

def _format_tinyfish_standings_search(payload: dict, language: str) -> str:
    """Render source evidence without implying it is a complete standings table."""
    league = html.escape(str(payload.get("league_name") or "League"))
    queried_at = html.escape(str(payload.get("queried_at") or "unknown"))
    if language == "uz":
        lines = [f"🔎 <b>{league} — jadval manbalari</b>",
                 "Bu to‘liq tasdiqlangan turnir jadvali emas; TinyFish qidiruv natijalari.",
                 f"Yangilangan (UTC): {queried_at}"]
        empty = "Foydalanish mumkin bo‘lgan manba topilmadi."
    elif language == "ru":
        lines = [f"🔎 <b>{league} — источники таблицы</b>",
                 "Это не полная подтверждённая таблица, а результаты поиска TinyFish.",
                 f"Обновлено (UTC): {queried_at}"]
        empty = "Подходящие источники не найдены."
    else:
        lines = [f"🔎 <b>{league} — standings sources</b>",
                 "These are TinyFish search results, not a verified complete table.",
                 f"Updated (UTC): {queried_at}"]
        empty = "No usable source results were found."

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        lines.append(empty)
        return "\n".join(lines)
    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        title = html.escape(str(item.get("title") or "Source")[:150])
        url = item.get("url")
        snippet = html.escape(str(item.get("snippet") or "")[:250])
        if isinstance(url, str) and url.startswith("https://"):
            lines.append(f'<a href="{html.escape(url, quote=True)}">{title}</a>')
        else:
            lines.append(title)
        if snippet:
            lines.append(snippet)
    return "\n".join(lines)[:3900]


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
