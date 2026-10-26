"""Handler-level tests with fake Telegram objects and real stores."""

import logging

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.menu import main_menu_handler
from app.bot.handlers.start import language_handler, start_handler
from app.bot.handlers.teams import (
    TeamSearchState,
    add_team,
    remove_team,
    search_team,
    show_my_teams,
    start_team_search,
)
from app.football.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import TeamResolver
from app.localization.i18n import text
from app.storage.database import StorageError
from app.storage.store import MemoryPreferenceStore
from tests.conftest import (
    make_callback,
    make_message,
    make_settings,
    make_team,
)
from tests.fakes import StubProvider

USER = 42
BARCA = make_team(529, "Barcelona", country="Spain")


class ScriptedProvider(StubProvider):
    def __init__(self, teams=None, error=None):
        self.teams = teams or []
        self.error = error
        self.calls = 0

    async def search_teams(self, query):
        self.calls += 1

        if self.error:
            raise self.error

        return list(self.teams)

    async def get_team_fixtures(self, *a):
        raise AssertionError

    async def get_live_events(self, *a):
        raise AssertionError


class BrokenStore(MemoryPreferenceStore):
    """Store whose database is down: every operation fails."""

    async def get_language(self, telegram_id):
        raise StorageError("down")

    async def set_language(self, telegram_id, language):
        raise StorageError("down")

    async def list_favorites(self, telegram_id):
        raise StorageError("down")

    async def add_favorite(self, *args, **kwargs):
        raise StorageError("down")

    async def remove_favorite(self, *args, **kwargs):
        raise StorageError("down")


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


def alert_text(callback) -> str | None:
    """Text of the alert shown via callback.answer(), if any."""
    if not callback.answer.await_args_list:
        return None

    args, kwargs = callback.answer.await_args
    return args[0] if args else kwargs.get("text")


def shown_text(callback) -> str:
    args, kwargs = callback.message.edit_text.await_args
    return args[0]


def button_data(callback) -> list[str]:
    _, kwargs = callback.message.edit_text.await_args
    return [
        b.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for b in row
    ]


# --- language -----------------------------------------------------------


async def test_language_choice_is_saved_and_applied_immediately(
    store, settings
):
    callback = make_callback("lang:ru")

    await language_handler(callback, store, settings)

    assert await store.get_language(USER) == "ru"
    assert text("welcome", "ru") == shown_text(callback)
    assert alert_text(callback) == text("language_saved", "ru")


async def test_invalid_language_is_rejected_and_not_saved(store, settings):
    for payload in ("lang:xx", "lang:", "lang:uz:extra", "lang:RU"):
        callback = make_callback(payload)
        await language_handler(callback, store, settings)

        assert await store.get_language(USER) is None
        callback.message.edit_text.assert_not_awaited()


async def test_language_not_saved_when_database_is_down(settings):
    callback = make_callback("lang:ru")

    await language_handler(callback, BrokenStore(), settings)

    # The user is told it failed; the UI does not switch language.
    assert alert_text(callback) == text("storage_error", "uz")
    callback.message.edit_text.assert_not_awaited()


async def test_start_keeps_saved_favorites_and_language(
    store, state, settings
):
    await store.set_language(USER, "en")
    await store.add_favorite(USER, 1, "Barcelona", limit=3)

    message = make_message("/start")
    await start_handler(message, state)

    assert await store.get_language(USER) == "en"
    assert len(await store.list_favorites(USER)) == 1
    message.answer.assert_awaited_once()


async def test_menu_uses_the_saved_language(store, state, settings):
    await store.set_language(USER, "ru")
    callback = make_callback("menu:main")

    await main_menu_handler(callback, state, store, settings)

    assert shown_text(callback) == text("welcome", "ru")


# --- searching ------------------------------------------------------------


async def test_search_results_open_the_team_page_with_id_only_buttons(
    store, state, settings, directory
):
    provider = ScriptedProvider([BARCA])
    message = make_message("Barcelona")
    await state.set_state(TeamSearchState.waiting_for_name)

    await search_team(
        message, state, store, settings,
        TeamResolver(provider), directory,
    )

    _, kwargs = message.answer.await_args
    data = [
        b.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    # A result opens the team page (info + fixtures); adding to
    # favorites happens from there, by id only.
    assert "team:view:529" in data
    assert all(len(d.encode("utf-8")) <= 64 for d in data)
    assert await state.get_state() is None
    assert await directory.get(529) == BARCA


@pytest.mark.parametrize("query", ["a", "ab", "  x "])
async def test_short_queries_do_not_use_the_api(
    query, store, state, settings, directory
):
    provider = ScriptedProvider([BARCA])
    message = make_message(query)

    await search_team(
        message, state, store, settings,
        TeamResolver(provider), directory,
    )

    assert provider.calls == 0
    assert message.answer.await_args.args[0] == text("query_too_short", "uz")


async def test_overlong_query_is_rejected(
    store, state, settings, directory
):
    provider = ScriptedProvider([BARCA])
    message = make_message("x" * 200)

    await search_team(
        message, state, store, settings,
        TeamResolver(provider), directory,
    )

    assert provider.calls == 0
    assert message.answer.await_args.args[0] == text("query_too_long", "uz")


async def test_no_match_keeps_the_user_in_search_mode(
    store, state, settings, directory
):
    message = make_message("Nonexistent FC")
    await state.set_state(TeamSearchState.waiting_for_name)

    await search_team(
        message, state, store, settings,
        TeamResolver(ScriptedProvider([])), directory,
    )

    assert message.answer.await_args.args[0] == text("no_teams_found", "uz")
    assert await state.get_state() == TeamSearchState.waiting_for_name.state


@pytest.mark.parametrize(
    "error, key",
    [
        (ProviderQuotaError("limit"), "provider_quota"),
        (ProviderAuthError("bad"), "provider_auth"),
        (ProviderUnavailableError("down"), "provider_unavailable"),
    ],
)
@pytest.mark.parametrize("language", ["uz", "ru", "en"])
async def test_provider_failures_show_a_localized_message_not_no_match(
    error, key, language, store, state, settings, directory
):
    await store.set_language(USER, language)
    message = make_message("Barcelona")

    await search_team(
        message, state, store, settings,
        TeamResolver(ScriptedProvider(error=error)), directory,
    )

    shown = message.answer.await_args.args[0]
    assert shown == text(key, language)
    assert shown != text("no_teams_found", language)


async def test_missing_api_key_is_reported_without_crashing(
    store, state, settings, directory, caplog
):
    caplog.set_level(logging.ERROR)
    message = make_message("Barcelona")

    await search_team(message, state, store, settings, None, directory)

    assert message.answer.await_args.args[0] == text("provider_auth", "uz")
    assert "API_FOOTBALL_KEY" in caplog.text


async def test_unexpected_resolver_crash_is_contained(
    store, state, settings, directory
):
    class Exploding:
        async def resolve(self, query):
            raise RuntimeError("bug")

    message = make_message("Barcelona")

    await search_team(
        message, state, store, settings, Exploding(), directory
    )

    assert message.answer.await_args.args[0] == text(
        "provider_unavailable", "uz"
    )


async def test_start_search_enters_waiting_state(
    store, state, settings
):
    callback = make_callback("team:search")

    await start_team_search(callback, state, store, settings)

    assert await state.get_state() == TeamSearchState.waiting_for_name.state


# --- adding favorites -----------------------------------------------------


async def test_add_favorite_persists_and_updates_the_view(
    store, settings, directory
):
    await directory.remember([BARCA])
    callback = make_callback("team:add:529")

    await add_team(callback, store, settings, directory)

    favorites = await store.list_favorites(USER)
    assert [(f.team_id, f.team_name) for f in favorites] == [
        (529, "Barcelona")
    ]
    assert text("team_added", "uz") in shown_text(callback)
    assert "team:rm:529" in button_data(callback)


async def test_duplicate_add_is_reported_and_not_stored_twice(
    store, settings, directory
):
    await directory.remember([BARCA])

    await add_team(make_callback("team:add:529"), store, settings, directory)
    again = make_callback("team:add:529")
    await add_team(again, store, settings, directory)

    assert alert_text(again) == text("team_already_added", "uz")
    assert len(await store.list_favorites(USER)) == 1


async def test_limit_comes_from_settings_not_a_hardcoded_three(
    store, directory
):
    settings = make_settings(free_favorite_slots=2)
    teams = [make_team(i, f"Team {i}") for i in (1, 2, 3)]
    await directory.remember(teams)

    for team in teams[:2]:
        await add_team(
            make_callback(f"team:add:{team.id}"), store, settings, directory
        )

    blocked = make_callback("team:add:3")
    await add_team(blocked, store, settings, directory)

    assert alert_text(blocked) == text("team_limit", "uz", limit=2)
    assert "2" in alert_text(blocked)
    assert len(await store.list_favorites(USER)) == 2


async def test_default_limit_is_three(store, settings, directory):
    teams = [make_team(i, f"Team {i}") for i in (1, 2, 3, 4)]
    await directory.remember(teams)

    for team in teams[:3]:
        await add_team(
            make_callback(f"team:add:{team.id}"), store, settings, directory
        )

    blocked = make_callback("team:add:4")
    await add_team(blocked, store, settings, directory)

    assert alert_text(blocked) == text("team_limit", "uz", limit=3)


async def test_expired_search_fails_safely(store, settings, directory):
    callback = make_callback("team:add:529")  # never searched/remembered

    await add_team(callback, store, settings, directory)

    assert alert_text(callback) == text("search_expired", "uz")
    assert await store.list_favorites(USER) == []


@pytest.mark.parametrize(
    "payload",
    ["team:add:", "team:add:abc", "team:add:-1", "team:add:0",
     "team:add:99999999999999999999", "team:add:1:2:3"],
)
async def test_malformed_add_payloads_never_crash(
    payload, store, settings, directory
):
    callback = make_callback(payload)

    await add_team(callback, store, settings, directory)

    # Anything malformed fails safely with an alert: "invalid" for
    # garbage, "search expired" for payloads shaped like the old
    # "team:add:<id>:<name>" buttons.
    assert alert_text(callback) in {
        text("invalid_action", "uz"),
        text("search_expired", "uz"),
    }
    assert await store.list_favorites(USER) == []


async def test_buttons_from_older_versions_ask_to_search_again(
    store, settings, directory
):
    callback = make_callback("team:add:529:Barcelona")

    await add_team(callback, store, settings, directory)

    assert alert_text(callback) == text("search_expired", "uz")


async def test_database_failure_is_reported_not_faked(settings, directory):
    await directory.remember([BARCA])
    callback = make_callback("team:add:529")

    await add_team(callback, BrokenStore(), settings, directory)

    assert alert_text(callback) == text("storage_error", "uz")
    callback.message.edit_text.assert_not_awaited()


async def test_team_names_are_html_escaped(store, settings, directory):
    nasty = make_team(5, "<b>Bad</b> & Co")
    await directory.remember([nasty])
    callback = make_callback("team:add:5")

    await add_team(callback, store, settings, directory)

    shown = shown_text(callback)
    assert "&lt;b&gt;Bad&lt;/b&gt; &amp; Co" in shown
    assert "<b>Bad</b>" not in shown


# --- viewing and removing --------------------------------------------------


async def test_my_teams_lists_favorites_with_remove_buttons(
    store, state, settings
):
    await store.add_favorite(USER, 1, "Barcelona", limit=3)
    await store.add_favorite(USER, 2, "Liverpool", limit=3)
    callback = make_callback("menu:teams")

    await show_my_teams(callback, state, store, settings)

    shown = shown_text(callback)
    assert "Barcelona" in shown and "Liverpool" in shown
    assert {"team:rm:1", "team:rm:2", "team:search"} <= set(
        button_data(callback)
    )


async def test_my_teams_with_no_favorites(store, state, settings):
    callback = make_callback("menu:teams")

    await show_my_teams(callback, state, store, settings)

    assert text("no_teams", "uz") in shown_text(callback)


async def test_my_teams_leaves_search_mode(store, state, settings):
    await state.set_state(TeamSearchState.waiting_for_name)

    await show_my_teams(make_callback("menu:teams"), state, store, settings)

    assert await state.get_state() is None


async def test_my_teams_survives_a_database_outage(state, settings):
    callback = make_callback("menu:teams")

    await show_my_teams(callback, state, BrokenStore(), settings)

    assert shown_text(callback) == text("storage_error", "uz")


async def test_remove_favorite_persists_and_frees_the_slot(
    store, settings
):
    await store.add_favorite(USER, 1, "Barcelona", limit=3)
    await store.add_favorite(USER, 2, "Liverpool", limit=3)
    callback = make_callback("team:rm:1")

    await remove_team(callback, store, settings)

    assert [f.team_id for f in await store.list_favorites(USER)] == [2]
    assert text("team_removed", "uz") in shown_text(callback)


async def test_removing_twice_is_harmless(store, settings):
    await store.add_favorite(USER, 1, "Barcelona", limit=3)

    await remove_team(make_callback("team:rm:1"), store, settings)
    second = make_callback("team:rm:1")
    await remove_team(second, store, settings)

    assert text("team_not_in_favorites", "uz") in shown_text(second)
    assert await store.list_favorites(USER) == []


@pytest.mark.parametrize(
    "payload", ["team:rm:", "team:rm:x", "team:rm:-3", "team:rm:1:2"]
)
async def test_malformed_remove_payloads_never_crash(
    payload, store, settings
):
    await store.add_favorite(USER, 1, "Barcelona", limit=3)
    callback = make_callback(payload)

    await remove_team(callback, store, settings)

    assert alert_text(callback) == text("invalid_action", "uz")
    assert len(await store.list_favorites(USER)) == 1


async def test_remove_during_database_outage_is_reported(settings):
    callback = make_callback("team:rm:1")

    await remove_team(callback, BrokenStore(), settings)

    assert alert_text(callback) == text("storage_error", "uz")


async def test_one_users_removal_never_touches_another_users_data(
    store, settings
):
    await store.add_favorite(1, 10, "Barcelona", limit=3)
    await store.add_favorite(2, 10, "Barcelona", limit=3)

    await remove_team(make_callback("team:rm:10", user_id=1), store, settings)

    assert await store.list_favorites(1) == []
    assert len(await store.list_favorites(2)) == 1
