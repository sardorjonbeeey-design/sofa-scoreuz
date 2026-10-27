"""Whole chain with API-Football-shaped HTTP responses (no network).

HTTP mock -> ApiFootballProvider -> CachingFootballProvider
-> FootballService -> real Dispatcher/handlers -> Telegram messages.
"""

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText

from app.bot.bot import create_dispatcher
from app.football.api_football import ApiFootballProvider
from app.football.caching import CachingFootballProvider
from app.football.service import FootballService
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import TeamResolver
from app.storage.store import MemoryPreferenceStore
from tests.conftest import make_settings
from tests.test_api_football import SECRET_KEY
from tests.test_api_football_features import fixture_item, standing
from tests.fakes import FakeArchive, standings_archive_payload
from tests.test_dispatch_integration import RecordingSession, callback_update


class FakeApi:
    """Plays the part of v3.football.api-sports.io and records requests."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.fail_with: httpx.Response | None = None
        self.responses = {
            "/fixtures": self.fixtures,
            "/leagues": self.leagues,
            "/standings": self.standings,
            "/teams": self.teams,
        }

    def count(self, path: str) -> int:
        return sum(1 for p, _ in self.requests if p == path)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append((request.url.path, params))

        if self.fail_with is not None:
            return self.fail_with

        body = self.responses[request.url.path](params)

        return httpx.Response(
            200,
            json={"errors": [], "results": len(body), "response": body},
            headers={
                "x-ratelimit-requests-limit": "100",
                "x-ratelimit-requests-remaining": str(100 - len(self.requests)),
            },
        )

    def fixtures(self, params):
        if params.get("live") == "all":
            return [fixture_item(1, "2H", 67, 2, 1)]

        if "date" in params:
            item = fixture_item(2, "NS", None, None, None, id=140,
                                name="La Liga", country="Spain")
            return [item]

        return [fixture_item(3, "NS", None, None, None)]  # team fixtures

    def leagues(self, params):
        return [{
            "league": {"id": 39, "name": "Premier League", "type": "League"},
            "country": {"name": "England"},
            "seasons": [{"year": 2026, "current": True}],
        }]

    def standings(self, params):
        return [{"league": {"standings": [[
            standing(1, "Arsenal", 23), standing(2, "Chelsea", 20),
        ]]}}]

    def teams(self, params):
        return [{
            "team": {"id": 42, "name": "Arsenal", "country": "England", "founded": 1886},
            "venue": {"name": "Emirates Stadium", "city": "London", "capacity": 60704},
        }]


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def app(api):
    client = httpx.AsyncClient(
        base_url=ApiFootballProvider.BASE_URL,
        headers={"x-apisports-key": SECRET_KEY},
        transport=httpx.MockTransport(api),
    )
    provider = CachingFootballProvider(
        ApiFootballProvider(SECRET_KEY, client=client, retry_delay=0)
    )
    archive = FakeArchive({39: standings_archive_payload(39, "Premier League")})
    service = FootballService(provider, timezone="Asia/Tashkent", archive=archive)
    session = RecordingSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    dispatcher = create_dispatcher(
        make_settings(default_language="en"),
        store=MemoryPreferenceStore("en"),
        resolver=TeamResolver(provider),
        directory=TeamDirectory(),
        service=service,
    )

    class App:
        pass

    app = App()

    async def press(data, update_id=1):
        session.requests.clear()
        await dispatcher.feed_update(bot, callback_update(data, update_id))
        return [r for r in session.requests if isinstance(r, EditMessageText)]

    app.press = press
    return app


async def test_live_scores_from_api_json_reach_the_user(app, api):
    (edit,) = await app.press("menu:live")

    assert "Arsenal 2–1 Chelsea" in edit.text
    assert "67'" in edit.text
    assert api.requests[0] == ("/fixtures", {"live": "all"})


async def test_todays_matches_use_tashkent_time_and_date_parameters(app, api):
    (edit,) = await app.press("menu:today")

    assert "17:30" in edit.text  # 12:30 UTC -> Asia/Tashkent
    path, params = api.requests[0]
    assert path == "/fixtures"
    assert params["timezone"] == "Asia/Tashkent" and "date" in params


async def test_standings_use_the_archive_without_api_football_requests(app, api):
    (edit,) = await app.press("lg:39")
    assert "Arsenal" in edit.text and "Season 2026" in edit.text

    for update_id in range(2, 12):
        await app.press("lg:39", update_id)

    # The standings screen is archive-only; no API-Football calls are made.
    assert api.count("/leagues") == 0
    assert api.count("/standings") == 0


async def test_a_team_page_after_restart_costs_one_team_and_one_fixture_request(app, api):
    (edit,) = await app.press("team:view:42")

    assert "Emirates Stadium" in edit.text and "Founded: 1886" in edit.text
    await app.press("team:view:42", 2)

    assert api.count("/teams") == 1
    assert api.count("/fixtures") == 1


async def test_many_users_and_screens_stay_within_a_small_request_budget(app, api):
    for update_id in range(1, 21):
        await app.press("menu:live", update_id)
        await app.press("menu:today", 100 + update_id)

    assert api.count("/fixtures") == 2  # one live list + one daily list


async def test_http_429_shows_a_quota_message_and_stops_retrying(app, api):
    api.fail_with = httpx.Response(429, json={})

    for update_id in range(1, 6):
        (edit,) = await app.press("menu:live", update_id)

    assert "busy" in edit.text.lower() or "limit" in edit.text.lower()
    assert len(api.requests) == 1  # no retry storm, back-off after the first


async def test_http_200_with_an_errors_field_is_not_shown_as_empty(app, api):
    api.fail_with = httpx.Response(
        200,
        json={"errors": {"requests": "You have reached the request limit for the day."},
              "response": []},
    )

    (edit,) = await app.press("menu:today")

    assert "No matches found" not in edit.text
    assert "limit" in edit.text.lower()


async def test_bad_credentials_never_expose_the_key(app, api):
    api.fail_with = httpx.Response(
        200, json={"errors": {"token": "Error/Missing application key."}, "response": []}
    )

    (edit,) = await app.press("menu:live")

    assert SECRET_KEY not in edit.text and "application key" not in edit.text
    assert "unavailable" in edit.text.lower()


async def test_server_errors_are_retried_once_then_reported(app, api):
    api.fail_with = httpx.Response(503)

    (edit,) = await app.press("menu:live")

    assert len(api.requests) == 2  # one bounded retry, not a loop
    assert "try again" in edit.text.lower()
