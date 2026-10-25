"""Startup / shutdown ordering of ``run_application``."""

from types import SimpleNamespace

import pytest
from aiogram import Dispatcher

import app.main as app_main
from app.football.provider import FootballProvider
from app.storage.store import MemoryPreferenceStore
from tests.conftest import make_settings


class SpyStore(MemoryPreferenceStore):
    def __init__(self, events):
        super().__init__("uz")
        self.events = events

    async def close(self):
        self.events.append("store")


@pytest.fixture(autouse=True)
def detach_handler_routers():
    """Let several tests build a real Dispatcher in one process.

    The handler routers are module-level singletons and aiogram allows
    a router to belong to one dispatcher only. The application builds
    exactly one dispatcher per process, so only tests need this reset.
    """
    from app.bot.handlers import menu, start, teams

    for module in (start, menu, teams):
        module.router._parent_router = None

    yield


@pytest.fixture
def events(monkeypatch):
    log: list[str] = []

    # --- health server ---------------------------------------------
    async def fake_web_server(port=None):
        log.append("web-start")

        async def cleanup():
            log.append("web")

        return SimpleNamespace(cleanup=cleanup)

    monkeypatch.setattr(app_main, "start_web_server", fake_web_server)

    # --- storage ---------------------------------------------------
    async def fake_create_store(settings):
        log.append("store-start")
        return SpyStore(log)

    monkeypatch.setattr(app_main, "create_store", fake_create_store)

    # --- football provider -------------------------------------------
    class SpyProvider(FootballProvider):
        def __init__(self, api_key):
            log.append("provider-start")

        async def close(self):
            log.append("provider")

        async def search_teams(self, query):
            return []

        async def get_team_fixtures(self, *args):
            return []

        async def get_live_events(self, *args):
            return []

    monkeypatch.setattr(app_main, "ApiFootballProvider", SpyProvider)

    # --- bot ---------------------------------------------------------
    real_create_bot = app_main.create_bot

    def spy_create_bot(token):
        bot = real_create_bot(token)
        original = bot.session.close

        async def close():
            log.append("bot")
            await original()

        bot.session.close = close
        return bot

    monkeypatch.setattr(app_main, "create_bot", spy_create_bot)

    # --- scheduler -----------------------------------------------------
    real_create_scheduler = app_main.create_scheduler

    def spy_create_scheduler(settings):
        scheduler = real_create_scheduler(settings)
        original = scheduler.shutdown

        def shutdown(*args, **kwargs):
            log.append("scheduler")
            return original(*args, **kwargs)

        scheduler.shutdown = shutdown
        return scheduler

    monkeypatch.setattr(app_main, "create_scheduler", spy_create_scheduler)

    # --- polling ---------------------------------------------------------
    async def fake_polling(self, *bots, **kwargs):
        log.append("polling")

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)

    return log


async def test_components_start_once_and_stop_in_reverse_order(events):
    await app_main.run_application(make_settings(), port=0)

    assert events.count("polling") == 1          # no duplicate loops
    assert events.count("web-start") == 1        # one health server
    assert events == [
        "web-start",
        "store-start",
        "provider-start",
        "polling",
        # shutdown: reverse of start-up
        "scheduler",
        "bot",
        "provider",
        "store",
        "web",
    ]


async def test_resources_are_released_when_polling_crashes(
    events, monkeypatch
):
    async def crashing_polling(self, *bots, **kwargs):
        events.append("polling")
        raise RuntimeError("boom")

    monkeypatch.setattr(Dispatcher, "start_polling", crashing_polling)

    with pytest.raises(RuntimeError, match="boom"):
        await app_main.run_application(make_settings(), port=0)

    for resource in ("scheduler", "bot", "provider", "store", "web"):
        assert resource in events


async def test_failed_startup_never_starts_polling_and_cleans_up(events):
    # An empty token fails after the web server and store started.
    with pytest.raises(ValueError, match="BOT_TOKEN"):
        await app_main.run_application(
            make_settings(bot_token=""), port=0
        )

    assert "polling" not in events
    assert "store" in events and "web" in events
    assert "provider" in events


async def test_bot_runs_without_football_key_but_search_is_disabled(
    events,
):
    await app_main.run_application(
        make_settings(api_football_key=""), port=0
    )

    assert "provider-start" not in events
    assert events.count("polling") == 1
