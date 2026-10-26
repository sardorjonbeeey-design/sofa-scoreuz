"""Message formatting: escaping, time zones, pagination, languages."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.bot.formatting import (
    PAGE_CHAR_BUDGET,
    build_match_pages,
    filter_scope,
    fixture_line,
    format_standings,
    format_team_page,
    freshness_footer,
    status_label,
)
from app.football.models import Team
from app.football.service import LeagueStandings, TeamMatches
from app.localization.i18n import SUPPORTED_LANGUAGES, TEXTS
from tests.fakes import UTC, make_fixture, make_table
from app.football.models import League

TASHKENT = ZoneInfo("Asia/Tashkent")


def test_a_scheduled_match_shows_the_kickoff_in_the_display_timezone():
    f = make_fixture(1, "Arsenal", "Chelsea", start=datetime(2026, 10, 26, 12, 30, tzinfo=UTC))

    assert "17:30" in fixture_line(f, "en", TASHKENT)  # UTC+5
    assert "12:30" in fixture_line(f, "en", UTC)


def test_a_live_match_shows_minute_and_score():
    f = make_fixture(1, "Arsenal", "Chelsea", status="2H", elapsed=67, goals=(2, 1))

    line = fixture_line(f, "en", UTC)

    assert "67'" in line and "Arsenal 2–1 Chelsea" in line and "🔴" in line


def test_half_time_and_full_time_are_labelled_in_the_users_language():
    ht = make_fixture(1, status="HT", goals=(0, 0))
    ft = make_fixture(2, status="FT", goals=(3, 2))

    assert "Перерыв" in fixture_line(ht, "ru", UTC)
    assert "Tugadi" in fixture_line(ft, "uz", UTC)
    assert "FT" in fixture_line(ft, "en", UTC)


def test_postponed_and_cancelled_matches_say_so_without_a_score():
    pst = make_fixture(1, "A", "B", status="PST")
    canc = make_fixture(2, "A", "B", status="CANC")

    assert "Postponed" in fixture_line(pst, "en", UTC)
    assert "Cancelled" in fixture_line(canc, "en", UTC)
    assert "–" in fixture_line(pst, "en", UTC) and "0" not in fixture_line(pst, "en", UTC)


def test_an_unknown_status_shows_its_raw_code_not_a_crash():
    assert status_label("ZZZ", "en") == "ZZZ"


def test_provider_text_is_html_escaped():
    f = make_fixture(1, "<b>Evil</b> & Co", "A<i>", competition="<script>")

    line = fixture_line(f, "en", UTC, with_competition=True)

    assert "<b>Evil" not in line and "&lt;b&gt;Evil" in line
    assert "<script>" not in line and "A<i>" not in line


def test_favorite_matches_are_marked():
    f = make_fixture(1, home_id=500)

    assert "⭐" in fixture_line(f, "en", UTC, favorite_ids={500})
    assert "⭐" not in fixture_line(f, "en", UTC, favorite_ids={999})


def test_match_dates_are_shown_when_asked():
    f = make_fixture(1, start=datetime(2026, 11, 1, 20, 0, tzinfo=UTC))

    assert fixture_line(f, "en", TASHKENT, with_date=True).startswith("02.11")


# --- grouping and pages ------------------------------------------------


def pages_for(fixtures, **kwargs):
    kwargs.setdefault("language", "en")
    kwargs.setdefault("tz", UTC)
    return build_match_pages(fixtures, **kwargs)


def test_no_matches_means_no_pages():
    assert pages_for([]) == []


def test_featured_leagues_come_before_unlisted_ones():
    fixtures = [
        make_fixture(1, competition="Minor Cup", league_id=99999, country="Nowhere"),
        make_fixture(2, competition="Premier League", league_id=39),
        make_fixture(3, competition="UEFA Champions League", league_id=2, country="World"),
    ]

    page = pages_for(fixtures)[0]

    assert page.index("UEFA Champions League") < page.index("Premier League") < page.index("Minor Cup")


def test_favorite_matches_come_first_and_appear_once():
    fixtures = [
        make_fixture(1, "Other A", "Other B"),
        make_fixture(2, "Mine", "Rival", home_id=500),
    ]

    page = pages_for(fixtures, favorite_ids={500})[0]

    assert page.index("Mine") < page.index("Other A")
    assert page.count("Mine") == 1
    assert "My teams" in page


def test_a_large_matchday_is_split_into_pages_within_the_limit():
    fixtures = [
        make_fixture(
            i, f"Home Team Number {i}", f"Away Team Number {i}",
            competition=f"League {i % 7}", league_id=1000 + i % 7, country=f"Country {i % 7}",
        )
        for i in range(400)
    ]

    pages = pages_for(fixtures)

    assert len(pages) > 1
    assert all(len(p) <= PAGE_CHAR_BUDGET + 200 for p in pages)
    assert all(len(p) < 4096 for p in pages)
    joined = "\n".join(pages)
    assert all(f"Home Team Number {i} " in joined for i in range(400))
    assert joined.count("Home Team Number 7 ") == 1  # nothing duplicated


def test_a_competition_header_is_repeated_when_it_continues_on_the_next_page():
    fixtures = [make_fixture(i, f"H{i}", f"A{i}") for i in range(60)]

    pages = pages_for(fixtures, budget=300)

    assert len(pages) > 1
    assert all(p.startswith("<b>Premier League") for p in pages)


def test_top_scope_keeps_featured_uzbek_and_favorite_matches_only():
    fixtures = [
        make_fixture(1, league_id=39),
        make_fixture(2, league_id=555, competition="Super League", country="Uzbekistan"),
        make_fixture(3, league_id=777, competition="Obscure", country="Nowhere"),
        make_fixture(4, league_id=778, competition="Obscure", country="Nowhere", home_id=500),
    ]

    top = {f.id for f in filter_scope(fixtures, True, {500})}

    assert top == {1, 2, 4}
    assert len(filter_scope(fixtures, False, {500})) == 4


def test_footer_reports_update_time_and_staleness():
    moment = datetime(2026, 10, 26, 12, 30, tzinfo=UTC).timestamp()

    fresh = freshness_footer(moment, False, language="en", tz=TASHKENT, tz_name="Asia/Tashkent")
    stale = freshness_footer(moment, True, language="en", tz=TASHKENT, tz_name="Asia/Tashkent")

    assert "17:30" in fresh and "Asia/Tashkent" in fresh and "Could not refresh" not in fresh
    assert "Could not refresh" in stale


# --- standings -----------------------------------------------------------


LEAGUE = League(39, "Premier League", "England", "League", None, 2026)


def test_standings_table_has_ranks_points_and_localized_headers():
    view = LeagueStandings(LEAGUE, 2026, (make_table("Arsenal", "Chelsea"),))

    assert "Pts" in format_standings(view, "en")
    assert "О" in format_standings(view, "ru") and "Команда" in format_standings(view, "ru")
    assert "Och" in format_standings(view, "uz")
    body = format_standings(view, "en")
    assert "Arsenal" in body and "Premier League" in body and "2026" in body


def test_standings_html_is_escaped_and_long_names_trimmed():
    view = LeagueStandings(LEAGUE, 2026, (make_table("<b>A Very Long Football Club Name</b>"),))

    body = format_standings(view, "en")

    assert "<b>A Very" not in body
    assert "&lt;b&gt;" in body


def test_a_cup_with_many_groups_stays_under_the_telegram_limit():
    groups = tuple(
        make_table(*[f"Team {g}-{i}" for i in range(1, 21)], group=f"Group {g}")
        for g in range(1, 9)
    )

    body = format_standings(LeagueStandings(LEAGUE, 2026, groups), "en")

    assert len(body) < 4096
    assert "Group 1" in body


def test_missing_standings_say_so_instead_of_inventing_a_table():
    assert "No table" in format_standings(LeagueStandings(LEAGUE, 2026, ()), "en")
    assert "No table" in format_standings(LeagueStandings(None, None, ()), "en")


# --- team page ---------------------------------------------------------------


def test_team_page_lists_details_upcoming_and_recent_matches():
    team = Team(42, "Arsenal", country="England", founded=1886,
                venue_name="Emirates Stadium", venue_city="London", venue_capacity=60704)
    matches = TeamMatches(
        upcoming=(make_fixture(1, "Arsenal", "Chelsea"),),
        recent=(make_fixture(2, "Arsenal", "Spurs", status="FT", goals=(2, 0)),),
    )

    page = format_team_page(team, "en", UTC, matches)

    for expected in ("Arsenal", "England", "Emirates Stadium", "London", "60 704",
                     "Founded: 1886", "Upcoming matches", "Recent results", "2–0"):
        assert expected in page, expected


def test_team_page_with_no_data_omits_lines_instead_of_printing_none():
    page = format_team_page(Team(1, "Mystery FC"), "en", UTC, TeamMatches((), ()))

    assert "None" not in page
    assert "No upcoming matches found." in page and "No recent results found." in page
    assert "Stadium" not in page and "Founded" not in page


def test_team_page_when_fixtures_could_not_be_loaded_says_so():
    page = format_team_page(Team(1, "Mystery FC"), "en", UTC, None)

    assert "Could not load the match list" in page


# --- languages -------------------------------------------------------------------


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_every_status_label_exists_in_every_language(language):
    for status in ("HT", "FT", "AET", "PEN", "PST", "CANC", "ABD", "SUSP", "INT", "TBD", "LIVE"):
        assert f"status_{status}" in TEXTS[language]


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_formatted_screens_render_in_each_language_without_leaks(language):
    f = make_fixture(1, "Arsenal", "Chelsea", status="FT", goals=(1, 0))
    view = LeagueStandings(LEAGUE, 2026, (make_table("Arsenal"),))
    team = format_team_page(Team(1, "Arsenal"), language, UTC, TeamMatches((f,), (f,)))
    screens = [
        fixture_line(f, language, UTC),
        format_standings(view, language),
        team,
        *build_match_pages([f], language=language, tz=UTC),
    ]

    for screen in screens:
        assert "None" not in screen
        assert "{" not in screen and "}" not in screen
