"""Live, today, standings, team pages, news, settings and navigation."""

import inspect
from datetime import datetime

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import football, menu, start, teams
from app.bot.handlers.teams import TeamSearchState
from app.football.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from app.football.leagues import FEATURED_LEAGUES
from app.football.models import League, Team
from app.football.service import CacheTimes
from app.football.team_directory import TeamDirectory
from app.localization.i18n import SUPPORTED_LANGUAGES, text
from app.storage.store import MemoryPreferenceStore
from tests.conftest import make_callback, make_settings
from tests.fakes import UTC, FakeFootball, make_fixture, make_table
from tests.test_football_service import Clock, make_service
from tests.test_handlers import BrokenStore

USER = 42
ARSENAL = Team(42, "Arsenal", country="England", founded=1886,
               venue_name="Emirates Stadium", venue_city="London")
PL = League(39, "Premier League", "England", "League", None, 2026)
ROUTERS = (start.router, menu.router, teams.router, football.router)


@pytest.fixture
def store():
    return MemoryPreferenceStore("uz")


@pytest.fixture
def directory():
    return TeamDirectory()


@pytest.fixture
def state():
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=USER, user_id=USER),
    )


@pytest.fixture
def settings():
    return make_settings(default_language="en")


@pytest.fixture
def world():
    """A fake provider with a little of everything."""
    provider = FakeFootball()
    provider.live = [make_fixture(1, "Arsenal", "Chelsea", home_id=42, status="2H",
                                  elapsed=67, goals=(2, 1))]
    provider.by_date = [
        make_fixture(2, "Real Madrid", "Barcelona", competition="La Liga",
                     league_id=140, country="Spain"),
        make_fixture(3, "Nobody FC", "Somebody FC", competition="Tiny League",
                     league_id=99999, country="Nowhere"),
    ]
    provider.team_fixtures = [
        make_fixture(4, "Arsenal", "Spurs", home_id=42),
        make_fixture(5, "Arsenal", "Everton", home_id=42, status="FT", goals=(3, 0),
                     start=datetime(2026, 10, 20, 12, 0, tzinfo=UTC)),
    ]
    provider.leagues[39] = PL
    provider.tables[39] = [make_table("Arsenal", "Chelsea")]
    provider.country_leagues = [
        League(777, "Super League", "Uzbekistan", "League", None, 2026),
    ]
    provider.leagues[777] = provider.country_leagues[0]
    provider.tables[777] = [make_table("Pakhtakor", "Nasaf")]
    provider.teams[42] = ARSENAL
    return provider


@pytest.fixture
def service(world):
    return make_service(world)[0]


def edited(callback):
    args, kwargs = callback.message.edit_text.await_args
    return args[0], kwargs.get("reply_markup")


def buttons(callback) -> list[str]:
    _, markup = edited(callback)
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def alert(callback) -> str | None:
    if not callback.answer.await_args_list:
        return None
    args, kwargs = callback.answer.await_args
    return args[0] if args else kwargs.get("text")


async def press(data, *, store, state, settings, directory, service, user=USER):
    """Route ``data`` through the real routers, as Telegram would."""
    callback = make_callback(data, user_id=user)
    kwargs = dict(callback=callback, state=state, store=store,
                  settings=settings, directory=directory, service=service)

    for router in ROUTERS:
        for handler in router.callback_query.handlers:
            matched, _ = await handler.check(callback)

            if matched:
                names = inspect.signature(handler.callback).parameters
                await handler.callback(**{k: v for k, v in kwargs.items() if k in names})
                return callback

    raise AssertionError(f"no handler answers {data!r}")


@pytest.fixture
def tap(store, state, settings, directory, service):
    async def _tap(data, **overrides):
        args = dict(store=store, state=state, settings=settings,
                    directory=directory, service=service)
        args.update(overrides)
        return await press(data, **args)

    return _tap


# --- live scores ---------------------------------------------------------------


async def test_live_scores_show_matches_scores_and_minutes(tap):
    callback = await tap("menu:live")

    body, _ = edited(callback)

    assert "Live matches" in body
    assert "67'" in body and "Arsenal 2–1 Chelsea" in body
    assert "Updated:" in body


async def test_live_buttons_offer_refresh_and_back_without_all_leagues(tap):
    data = buttons(await tap("menu:live"))

    assert "fx:l:a:0" not in data
    assert "fx:l:t:0" in data  # refresh
    assert "menu:main" in data
    assert all(len(d.encode()) <= 64 for d in data)


async def test_no_live_matches_says_so(tap, world):
    world.live = []

    body, _ = edited(await tap("menu:live"))

    assert "No live matches right now." in body


async def test_live_matches_outside_coverage_are_never_shown(tap, world):
    world.live = [make_fixture(9, status="1H", elapsed=3, league_id=99999,
                               competition="Tiny", country="Nowhere")]

    body, _ = edited(await tap("menu:live"))

    assert "No matches in the selected major leagues" in body

    body, _ = edited(await tap("fx:l:a:0"))
    assert "Tiny" not in body


async def test_live_scores_are_shared_between_users(tap, world):
    for user in (1, 2, 3, 4, 5):
        callback = await tap("menu:live", user=user)
        assert "Arsenal 2–1 Chelsea" in edited(callback)[0]

    assert world.calls["live"] == 1  # one provider request, five users


async def test_my_teams_are_highlighted_and_listed_first(tap, store, world):
    await store.add_favorite(USER, 42, "Arsenal", 3)
    world.live.append(make_fixture(8, "Zeta", "Alpha", status="1H", elapsed=1,
                                   league_id=2, competition="UEFA Champions League",
                                   country="World"))

    body, _ = edited(await tap("menu:live"))

    assert "My teams" in body
    assert body.index("Arsenal") < body.index("Zeta")
    assert "⭐" in body


# --- today's matches -----------------------------------------------------------


async def test_todays_matches_show_kickoff_in_the_display_timezone(tap, service):
    service.now_local = lambda: datetime(2026, 10, 26, 9, 0, tzinfo=service.tz)

    body, _ = edited(await tap("menu:today"))

    assert "26.10.2026" in body
    assert "Real Madrid – Barcelona" in body
    assert "17:30" in body  # 12:30 UTC in Tashkent
    assert "Nobody FC" not in body  # not a top league


async def test_the_old_matches_button_id_still_works(tap):
    body, _ = edited(await tap("menu:matches"))

    assert "Today's matches" in body


async def test_legacy_today_all_scope_callback_still_obeys_coverage(tap):
    body, _ = edited(await tap("fx:d:a:0"))

    assert "Nobody FC" not in body and "Real Madrid" in body


async def test_empty_today_says_so(tap, world):
    world.by_date = []

    body, _ = edited(await tap("menu:today"))

    assert "No matches found for today." in body


async def test_long_lists_paginate_with_working_navigation(tap, world):
    world.by_date = [
        make_fixture(100 + i, f"Home Team Number {i}", f"Away Team Number {i}",
                     competition="Premier League", league_id=39,
                     country="England")
        for i in range(300)
    ]

    first = await tap("fx:d:a:0")
    body, _ = edited(first)
    assert "📄 1/" in body and "fx:d:a:1" in buttons(first)
    assert "fx:d:a:-1" not in buttons(first)
    assert len(body) < 4096

    second = await tap("fx:d:a:1")
    assert "📄 2/" in edited(second)[0]
    assert "fx:d:a:0" in buttons(second)  # back to previous page


async def test_a_page_past_the_end_shows_the_last_page(tap):
    body, _ = edited(await tap("fx:d:a:999"))

    assert "Real Madrid" in body


@pytest.mark.parametrize("data", ["fx:", "fx:x:t:0", "fx:l:t:-1", "fx:l:t:abc", "fx:l:t:0:9"])
async def test_malformed_match_list_payloads_are_rejected_safely(tap, data):
    callback = await tap(data)

    assert alert(callback) == text("invalid_action", "en")
    callback.message.edit_text.assert_not_awaited()


# --- provider failures ---------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (ProviderQuotaError("INTERNAL-quota-detail-7731"), "provider_quota"),
        (ProviderAuthError("INTERNAL-auth-detail-7731"), "provider_auth"),
        (ProviderUnavailableError("INTERNAL-down-detail-7731"), "provider_unavailable"),
    ],
)
@pytest.mark.parametrize("entry", ["menu:live", "menu:today", "menu:standings"])
async def test_provider_failures_show_a_clear_message_with_a_way_out(tap, world, error, key, entry):
    world.error = error
    callback = await tap(entry if entry != "menu:standings" else "lg:39")

    body, _ = edited(callback)

    # A short localized message; internal details never reach the user.
    assert body == text(key, "en")
    assert str(error) not in body
    assert {"menu:main", "menu:standings"} & set(buttons(callback))


async def test_failure_screens_offer_a_retry_that_returns_to_the_same_screen(tap, world):
    world.error = ProviderUnavailableError("down")

    data = buttons(await tap("menu:live"))

    assert "fx:l:t:0" in data


async def test_without_an_api_key_the_features_say_unavailable(tap):
    for entry in ("menu:live", "menu:today", "lg:39", "lgc:UZ"):
        callback = await tap(entry, service=None)
        assert edited(callback)[0] == text("provider_auth", "en")


async def test_todays_list_survives_a_provider_outage_with_a_stale_notice(store, state, settings, directory, world):
    clock = Clock()
    service, _, _ = make_service(world, clock=clock, times=CacheTimes(fixtures=300))
    args = dict(store=store, state=state, settings=settings, directory=directory, service=service)

    await press("menu:today", **args)
    clock.now += 400
    world.error = ProviderUnavailableError("down")
    body, _ = edited(await press("menu:today", **args))

    assert "Real Madrid" in body
    assert "Could not refresh the data" in body


async def test_live_scores_are_never_shown_stale(store, state, settings, directory, world):
    clock = Clock()
    service, _, _ = make_service(world, clock=clock, times=CacheTimes(live=60))
    args = dict(store=store, state=state, settings=settings, directory=directory, service=service)

    await press("menu:live", **args)
    clock.now += 61
    world.error = ProviderUnavailableError("down")
    body, _ = edited(await press("menu:live", **args))

    assert body == text("provider_unavailable", "en")
    assert "Arsenal" not in body


async def test_an_outage_does_not_hammer_the_provider(tap, world):
    world.error = ProviderQuotaError("limit")

    for _ in range(10):
        await tap("menu:live")

    assert world.calls["live"] == 1


# --- standings -----------------------------------------------------------------


async def test_league_menu_lists_every_featured_competition_and_uzbekistan(tap):
    data = buttons(await tap("menu:standings"))

    for league in FEATURED_LEAGUES:
        assert f"lg:{league.id}" in data
    assert "lgc:UZ" in data and "menu:main" in data


async def test_league_table_shows_standings(tap):
    callback = await tap("lg:39")

    body, _ = edited(callback)

    assert "Premier League" in body and "Arsenal" in body and "Chelsea" in body
    assert "Pts" in body and "Season 2026" in body
    assert "menu:standings" in buttons(callback)


async def test_a_league_without_a_table_says_so(tap, world):
    world.tables[39] = []

    body, _ = edited(await tap("lg:39"))

    assert "No table is available" in body


async def test_uzbek_leagues_come_from_the_provider(tap):
    callback = await tap("lgc:UZ")

    body, _ = edited(callback)

    assert "Uzbekistan" in body
    assert "lg:777" in buttons(callback)

    assert "Pakhtakor" in edited(await tap("lg:777"))[0]


async def test_country_without_leagues_says_so(tap, world):
    world.country_leagues = []

    body, _ = edited(await tap("lgc:UZ"))

    assert body == text("no_country_leagues", "en")


async def test_forged_league_ids_never_reach_the_provider(tap, world):
    callback = await tap("lg:31337")

    assert alert(callback) == text("invalid_action", "en")
    assert "standings" not in world.calls


@pytest.mark.parametrize("data", ["lg:0", "lg:abc", "lg:", "lgc:xx", "lgc:", "lgc:UZZ"])
async def test_malformed_league_payloads_are_rejected(tap, data):
    callback = await tap(data)

    assert alert(callback) == text("invalid_action", "en")


async def test_standings_are_cached_across_users(tap, world):
    await tap("lg:39")
    await tap("lg:39")

    assert world.calls["standings"] == 1


# --- team search results -> team page ---------------------------------------------


async def test_team_page_shows_details_fixtures_and_results(tap, directory):
    await directory.remember([ARSENAL])

    callback = await tap("team:view:42")
    body, _ = edited(callback)

    for expected in ("Arsenal", "England", "Emirates Stadium", "Founded: 1886",
                     "Upcoming matches", "Spurs", "Recent results", "3–0"):
        assert expected in body, expected
    assert "team:add:42" in buttons(callback)
    assert "menu:teams" in buttons(callback)


async def test_team_page_offers_removal_for_favorites(tap, store, directory):
    await directory.remember([ARSENAL])
    await store.add_favorite(USER, 42, "Arsenal", 3)

    data = buttons(await tap("team:view:42"))

    assert "team:rm:42" in data and "team:add:42" not in data


async def test_team_page_works_after_a_restart_via_the_provider(tap):
    # The in-memory search results are gone (empty directory).
    body, _ = edited(await tap("team:view:42"))

    assert "Emirates Stadium" in body


async def test_team_page_still_opens_when_fixtures_fail(tap, directory, world):
    await directory.remember([ARSENAL])
    world.error = ProviderUnavailableError("down")

    body, _ = edited(await tap("team:view:42"))

    assert "Arsenal" in body and "Could not load the match list" in body


async def test_a_saved_team_opens_even_if_the_provider_is_down(tap, store, world):
    await store.add_favorite(USER, 777, "Pakhtakor", 3)
    world.error = ProviderUnavailableError("down")

    body, _ = edited(await tap("team:view:777"))

    assert "Pakhtakor" in body


async def test_an_unidentifiable_team_fails_safely(tap):
    callback = await tap("team:view:999999")

    assert alert(callback) == text("search_expired", "en")


@pytest.mark.parametrize("data", ["team:view:", "team:view:abc", "team:view:0", "team:view:-3"])
async def test_malformed_team_page_payloads_are_rejected(tap, data):
    assert alert(await tap(data)) == text("invalid_action", "en")


async def test_team_page_reports_a_database_outage(tap, directory):
    await directory.remember([ARSENAL])

    callback = await tap("team:view:42", store=BrokenStore("uz"))

    assert alert(callback) == text("storage_error", "en")


async def test_adding_from_a_restarted_bot_uses_the_provider_for_the_name(tap, store):
    await tap("team:add:42")

    assert [f.team_name for f in await store.list_favorites(USER)] == ["Arsenal"]


async def test_favorites_rows_open_the_team_or_remove_it(tap, store):
    await store.add_favorite(USER, 42, "Arsenal", 3)

    data = buttons(await tap("menu:teams"))

    assert "team:view:42" in data and "team:rm:42" in data


async def test_the_search_prompt_has_a_way_out_that_leaves_search_mode(tap, state):
    callback = await tap("team:search")

    assert await state.get_state() == TeamSearchState.waiting_for_name.state
    assert "menu:teams" in buttons(callback)

    await tap("menu:teams")

    assert await state.get_state() is None


async def test_menu_buttons_leave_search_mode(tap, state):
    await state.set_state(TeamSearchState.waiting_for_name)

    await tap("menu:live")

    assert await state.get_state() is None


# --- news and settings (language) -----------------------------------------------------


async def test_news_screen_uses_localized_unavailable_fallback(tap, monkeypatch):
    async def no_news(**kwargs):
        return ()

    monkeypatch.setattr(menu, "football_news", no_news)
    callback = await tap("menu:news")

    body, _ = edited(callback)

    assert text("news_unavailable", "en") in body
    assert "menu:main" in buttons(callback)


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_the_main_menu_shows_news_without_unfinished_marker(language):
    labels = [b.text for row in menu.main_menu(language).inline_keyboard for b in row]

    assert text("news", language) in labels
    assert not any("🚧" in label for label in labels)


async def test_settings_lets_the_user_switch_language(tap, store, state):
    callback = await tap("menu:settings")

    body, _ = edited(callback)
    data = buttons(callback)

    assert "Asia/Tashkent" in body
    assert {"lang:uz", "lang:ru", "lang:en"} <= set(data)

    switched = await tap("lang:ru")

    assert await store.get_language(USER) == "ru"
    assert edited(switched)[0] == text("welcome", "ru")
    assert any(
        b.text == text("live", "ru")
        for row in edited(switched)[1].inline_keyboard
        for b in row
    )


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
async def test_every_screen_is_shown_in_the_users_language(tap, store, language, monkeypatch):
    async def no_news(**kwargs):
        return ()

    monkeypatch.setattr(menu, "football_news", no_news)
    await store.set_language(USER, language)

    for entry, key in (("menu:live", "live_title"), ("menu:news", "news_unavailable"),
                       ("menu:standings", "standings_pick"), ("menu:settings", "settings_title")):
        body, _ = edited(await tap(entry))
        assert body.startswith(text(key, language).split("{")[0]), (entry, language)


# --- navigation ------------------------------------------------------------------------


async def test_every_button_reachable_from_the_menu_leads_somewhere(tap, store, directory, monkeypatch):
    """Crawl the whole UI: no dead buttons, no crashes, no placeholders."""
    async def no_news(**kwargs):
        return ()

    monkeypatch.setattr(menu, "football_news", no_news)
    monkeypatch.setattr(teams, "football_news", no_news)
    await store.add_favorite(USER, 42, "Arsenal", 3)
    await directory.remember([ARSENAL])
    seen, queue, pressed = set(), ["menu:main"], 0

    while queue:
        data = queue.pop(0)

        if data in seen:
            continue

        seen.add(data)
        callback = await tap(data)  # raises if no handler / handler crashes
        pressed += 1

        if callback.message.edit_text.await_args is None:
            assert alert(callback), f"{data} did nothing"
            continue

        body, markup = edited(callback)
        assert "coming soon" not in body.lower() and "tez orada" not in body
        assert "скоро будет" not in body

        for row in markup.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64
                queue.append(button.callback_data)

    # menu, live, today, standings (+14 leagues, UZ), news, settings, ...
    assert pressed >= 25
    assert {"menu:live", "menu:today", "menu:standings", "menu:news",
            "menu:settings", "team:search", "menu:teams"} <= seen
