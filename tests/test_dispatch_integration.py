"""Real aiogram Dispatcher, real routers, real dependency injection.

Handler tests call the functions directly. This feeds genuine Telegram
``Update`` objects through ``create_dispatcher`` (as polling would) with
a fake network session, so routing filters, FSM state, dependency
injection by parameter name and the Bot -> API binding are exercised
together. No Telegram or API-Football traffic happens.
"""

from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.bot import create_dispatcher
from app.bot.handlers import menu
from app.football.leagues import FEATURED_LEAGUES
from app.football.news import NewsItem
from app.football.models import League, Team
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import TeamResolver
from app.storage.store import MemoryPreferenceStore
from tests.conftest import make_settings
from tests.fakes import FakeFootball, make_fixture, make_table
from tests.test_football_service import make_service

USER = User(id=42, is_bot=False, first_name="Tester")
CHAT = Chat(id=42, type="private")


class RecordingSession(BaseSession):
    """Records every Bot API call instead of sending it."""

    def __init__(self):
        super().__init__()
        self.requests = []

    async def close(self):
        return None

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


def message(text=None, message_id=1) -> Message:
    return Message(message_id=message_id, date=datetime.now(), chat=CHAT, from_user=USER, text=text)


def callback_update(data: str, update_id=1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id), from_user=USER, chat_instance="x",
            data=data, message=message("menu"),
        ),
    )


@pytest.fixture
def world():
    provider = FakeFootball()
    provider.live = [make_fixture(1, "Arsenal", "Chelsea", status="2H", elapsed=67, goals=(2, 1))]
    provider.by_date = [make_fixture(2, "Real Madrid", "Barcelona")]
    provider.team_fixtures = [make_fixture(3, "Arsenal", "Spurs", home_id=42)]
    provider.leagues[39] = League(39, "Premier League", "England", "League", None, 2026)
    provider.tables[39] = [make_table("Arsenal", "Chelsea")]
    provider.teams[42] = Team(42, "Arsenal", country="England")
    return provider


@pytest.fixture
def app(world):
    session = RecordingSession()
    bot = Bot("123456:TEST-TOKEN", session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    service = make_service(world)[0]
    store = MemoryPreferenceStore("en")
    dispatcher = create_dispatcher(
        make_settings(default_language="en"),
        store=store,
        resolver=TeamResolver(service.provider),
        directory=TeamDirectory(),
        service=service,
    )

    class App:
        pass

    app = App()
    app.bot, app.session, app.dispatcher, app.store, app.world = bot, session, dispatcher, store, world

    async def feed(update):
        session.requests.clear()
        await dispatcher.feed_update(bot, update)
        return list(session.requests)

    app.feed = feed
    return app


def edits(requests):
    return [r for r in requests if isinstance(r, EditMessageText)]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("menu:live", "Arsenal 2–1 Chelsea"),
        ("menu:today", "Real Madrid"),
        ("menu:matches", "Real Madrid"),
        ("menu:standings", "Choose a competition"),
        ("lg:39", "Premier League"),
        ("menu:news", "Football news"),
        ("menu:settings", "Choose your language"),
        ("team:view:42", "Arsenal"),
        ("menu:teams", "My Teams"),
        ("team:search", "team"),
    ],
)
async def test_every_screen_is_reachable_through_the_real_dispatcher(app, data, expected, monkeypatch):
    async def sample_news(**kwargs):
        return (NewsItem("Top league update", "https://example.test/news", "Example"),)

    if data == "menu:news":
        monkeypatch.setattr(menu, "football_news", sample_news)
    requests = await app.feed(callback_update(data))

    sent = edits(requests)
    assert len(sent) == 1, [type(r).__name__ for r in requests]
    assert expected in sent[0].text
    assert any(isinstance(r, AnswerCallbackQuery) for r in requests)  # spinner cleared


async def test_start_command_shows_the_language_chooser(app):
    update = Update(update_id=1, message=message("/start"))

    requests = await app.feed(update)

    assert [type(r) for r in requests] == [SendMessage]


async def test_the_whole_favorite_journey_through_real_routing(app):
    """search -> result -> team page -> add -> list -> remove."""
    await app.feed(callback_update("team:search", 1))
    requests = await app.feed(Update(update_id=2, message=message("arsenal", 2)))
    # no resolver results from the stub (search not scripted) -> handled, not crashed
    assert requests

    await app.feed(callback_update("team:view:42", 3))
    await app.feed(callback_update("team:add:42", 4))

    assert [f.team_id for f in await app.store.list_favorites(42)] == [42]

    listing = edits(await app.feed(callback_update("menu:teams", 5)))[0]
    assert "Arsenal" in listing.reply_markup.inline_keyboard[0][0].text

    await app.feed(callback_update("team:rm:42", 6))

    assert await app.store.list_favorites(42) == []


@pytest.mark.parametrize("data", ["fx:zz", "lg:abc", "lgc:xx", "team:view:abc", "team:add:", "unknown:thing"])
async def test_garbage_callbacks_never_crash_the_dispatcher(app, data):
    # aiogram swallows handler exceptions into logs, so assert on behavior:
    # nothing is edited, and any answer is a short alert (or nothing).
    requests = await app.feed(callback_update(data))

    assert edits(requests) == []


async def test_forged_league_id_does_not_spend_api_quota(app):
    await app.feed(callback_update("lg:31337"))

    assert "standings" not in app.world.calls


async def test_the_same_screen_for_many_users_costs_one_api_request(app):
    for update_id in range(1, 11):
        await app.feed(callback_update("menu:live", update_id))

    assert app.world.calls["live"] == 1


async def test_without_an_api_key_the_dispatcher_still_serves_the_menu(world, monkeypatch):
    async def no_news(**kwargs):
        return ()

    monkeypatch.setattr(menu, "football_news", no_news)
    session = RecordingSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    dispatcher = create_dispatcher(make_settings(default_language="en"))

    await dispatcher.feed_update(bot, callback_update("menu:live"))
    await dispatcher.feed_update(bot, callback_update("menu:news", 2))

    texts = [r.text for r in session.requests if isinstance(r, EditMessageText)]
    assert any("unavailable" in t for t in texts)
    assert any("Could not load news" in t for t in texts)


def test_the_menu_covers_every_featured_league_button_id():
    # Guards the catalog against an id that cannot be encoded in a payload.
    assert all(isinstance(league.id, int) and league.id > 0 for league in FEATURED_LEAGUES)
