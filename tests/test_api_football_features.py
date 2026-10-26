"""New API-Football endpoints: parsing, malformed data, quota headers."""

import logging
from datetime import date

import httpx
import pytest

from app.football.errors import ProviderQuotaError
from tests.test_api_football import make_provider


def fixture_item(fixture_id=1, status="1H", elapsed=23, home=2, away=1, **league):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-10-26T12:30:00+00:00",
            "status": {"short": status, "elapsed": elapsed},
            "venue": {"name": "Emirates Stadium"},
        },
        "league": {
            "id": league.get("id", 39),
            "name": league.get("name", "Premier League"),
            "country": league.get("country", "England"),
        },
        "teams": {
            "home": {"id": 42, "name": "Arsenal", "logo": "a.png"},
            "away": {"id": 49, "name": "Chelsea", "logo": "c.png"},
        },
        "goals": {"home": home, "away": away},
    }


def ok(response, *, headers=None):
    return httpx.Response(
        200,
        json={"errors": [], "results": len(response), "response": response},
        headers=headers or {},
    )


async def test_live_fixtures_are_parsed_with_score_and_status():
    provider, calls = make_provider(lambda r, n: ok([fixture_item()]))

    fixtures = await provider.get_live_fixtures()

    assert dict(calls[0].url.params) == {"live": "all"}
    fixture = fixtures[0]
    assert (fixture.home_team.name, fixture.away_team.name) == (
        "Arsenal",
        "Chelsea",
    )
    assert (fixture.status, fixture.elapsed) == ("1H", 23)
    assert (fixture.home_goals, fixture.away_goals) == (2, 1)
    assert (fixture.league_id, fixture.league_country) == (39, "England")
    assert fixture.start_time.utcoffset().total_seconds() == 0


async def test_unstarted_fixture_has_no_score_not_zero_zero():
    item = fixture_item(status="NS", elapsed=None, home=None, away=None)
    provider, _ = make_provider(lambda r, n: ok([item]))

    fixture = (await provider.get_live_fixtures())[0]

    assert fixture.home_goals is None and fixture.away_goals is None
    assert fixture.elapsed is None


async def test_fixtures_by_date_send_the_date_and_timezone():
    provider, calls = make_provider(lambda r, n: ok([fixture_item()]))

    await provider.get_fixtures_by_date(date(2026, 10, 26), "Asia/Tashkent")

    assert dict(calls[0].url.params) == {
        "date": "2026-10-26",
        "timezone": "Asia/Tashkent",
    }


async def test_one_malformed_fixture_does_not_hide_the_others(caplog):
    broken = {"fixture": {"id": 7}}  # no teams, date or league
    provider, _ = make_provider(
        lambda r, n: ok([broken, fixture_item(2), {"nonsense": True}])
    )

    with caplog.at_level(logging.WARNING):
        fixtures = await provider.get_live_fixtures()

    assert [f.id for f in fixtures] == [2]
    assert "malformed" in caplog.text


async def test_leagues_by_id_detect_the_current_season():
    payload = [
        {
            "league": {"id": 39, "name": "Premier League", "type": "League"},
            "country": {"name": "England"},
            "seasons": [
                {"year": 2025, "current": False},
                {"year": 2026, "current": True},
            ],
        }
    ]
    provider, calls = make_provider(lambda r, n: ok(payload))

    league = (await provider.get_leagues(league_id=39))[0]

    assert dict(calls[0].url.params) == {"id": "39"}
    assert (league.name, league.country, league.current_season) == (
        "Premier League",
        "England",
        2026,
    )


async def test_leagues_by_country_ask_for_current_competitions_only():
    provider, calls = make_provider(lambda r, n: ok([]))

    assert await provider.get_leagues(country="Uzbekistan") == []
    assert dict(calls[0].url.params) == {
        "country": "Uzbekistan",
        "current": "true",
    }


async def test_leagues_need_a_filter():
    provider, calls = make_provider(lambda r, n: ok([]))

    with pytest.raises(ValueError):
        await provider.get_leagues()

    assert calls == []  # nothing was sent upstream


def standing(rank, name, points):
    return {
        "rank": rank,
        "team": {"id": 100 + rank, "name": name},
        "points": points,
        "goalsDiff": 5,
        "group": "Group A",
        "form": "WWDLW",
        "all": {
            "played": 10, "win": 7, "draw": 2, "lose": 1,
            "goals": {"for": 20, "against": 15},
        },
    }


async def test_standings_are_parsed_including_groups():
    payload = [
        {
            "league": {
                "standings": [
                    [standing(1, "Arsenal", 23), standing(2, "Chelsea", 20)],
                    [standing(1, "Roma", 18)],
                ]
            }
        }
    ]
    provider, calls = make_provider(lambda r, n: ok(payload))

    groups = await provider.get_standings(39, 2026)

    assert dict(calls[0].url.params) == {"league": "39", "season": "2026"}
    assert [len(g.rows) for g in groups] == [2, 1]
    assert groups[0].name == "Group A"
    row = groups[0].rows[0]
    assert (row.rank, row.team.name, row.points, row.goal_diff) == (
        1, "Arsenal", 23, 5,
    )
    assert (row.played, row.won, row.drawn, row.lost) == (10, 7, 2, 1)


async def test_no_published_table_is_an_empty_list():
    provider, _ = make_provider(lambda r, n: ok([]))

    assert await provider.get_standings(39, 2026) == []


async def test_malformed_standings_rows_are_skipped():
    payload = [{"league": {"standings": [[standing(1, "Arsenal", 23), {"rank": 2}]]}}]
    provider, _ = make_provider(lambda r, n: ok(payload))

    groups = await provider.get_standings(39, 2026)

    assert [r.team.name for r in groups[0].rows] == ["Arsenal"]


async def test_team_details_include_the_stadium():
    payload = [
        {
            "team": {"id": 42, "name": "Arsenal", "country": "England", "founded": 1886},
            "venue": {"name": "Emirates Stadium", "city": "London", "capacity": 60704},
        }
    ]
    provider, calls = make_provider(lambda r, n: ok(payload))

    team = await provider.get_team(42)

    assert dict(calls[0].url.params) == {"id": "42"}
    assert (team.founded, team.venue_name, team.venue_city, team.venue_capacity) == (
        1886, "Emirates Stadium", "London", 60704,
    )


async def test_unknown_team_is_none():
    provider, _ = make_provider(lambda r, n: ok([]))

    assert await provider.get_team(1) is None


async def test_http_200_with_a_quota_error_is_not_empty_data():
    body = {"errors": {"requests": "You have reached the request limit for the day."}, "response": []}
    provider, _ = make_provider(lambda r, n: httpx.Response(200, json=body))

    with pytest.raises(ProviderQuotaError):
        await provider.get_live_fixtures()


async def test_daily_quota_headers_are_recorded():
    headers = {
        "x-ratelimit-requests-limit": "100",
        "x-ratelimit-requests-remaining": "88",
    }
    provider, _ = make_provider(lambda r, n: ok([], headers=headers))

    await provider.get_live_fixtures()

    assert (provider.requests_limit, provider.requests_remaining) == (100, 88)


async def test_a_nearly_exhausted_quota_is_logged(caplog):
    headers = {
        "x-ratelimit-requests-limit": "100",
        "x-ratelimit-requests-remaining": "4",
    }
    provider, _ = make_provider(lambda r, n: ok([], headers=headers))

    with caplog.at_level(logging.WARNING):
        await provider.get_live_fixtures()

    assert "4 of 100" in caplog.text


async def test_missing_or_garbage_quota_headers_are_ignored():
    provider, _ = make_provider(
        lambda r, n: ok([], headers={"x-ratelimit-requests-remaining": "lots"})
    )

    await provider.get_live_fixtures()

    assert provider.requests_remaining is None
