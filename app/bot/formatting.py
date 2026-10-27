"""Turn football data into Telegram messages.

Pure functions (no I/O) so they are easy to test. The bot sends HTML,
so EVERY string that comes from the data provider is escaped here.
Missing data is left out; nothing is ever filled in with a guess.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime, tzinfo
from html import escape

from app.football.leagues import (
    featured_competition_ids,
    featured_country_names,
    league_priority,
)
from app.football.models import Fixture, StandingsGroup, Team
from app.football.service import LeagueStandings, TeamMatches
from app.football.status import (
    BREAK_STATUSES,
    FINISHED_STATUSES,
    LIVE_STATUSES,
    NOT_PLAYED_STATUSES,
)
from app.localization.i18n import text

# Telegram allows 4096 characters; leave room for title and footer.
PAGE_CHAR_BUDGET = 3300
MESSAGE_CHAR_LIMIT = 4000

TEAM_NAME_COLUMN = 14


def clock(moment: datetime, tz: tzinfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M")


def short_date(moment: datetime, tz: tzinfo) -> str:
    return moment.astimezone(tz).strftime("%d.%m")


def status_label(status: str, language: str) -> str:
    key = f"status_{status}"
    label = text(key, language)

    # ``text`` returns the key itself for unknown statuses.
    return status if label == key else label


def score(fixture: Fixture) -> str:
    if fixture.home_goals is None or fixture.away_goals is None:
        return "–"

    return f"{fixture.home_goals}–{fixture.away_goals}"


def fixture_line(
    fixture: Fixture,
    language: str,
    tz: tzinfo,
    *,
    with_date: bool = False,
    with_competition: bool = False,
    favorite_ids: Iterable[int] = (),
) -> str:
    home = escape(fixture.home_team.name)
    away = escape(fixture.away_team.name)
    status = fixture.status
    marker = (
        "⭐ "
        if {fixture.home_team.id, fixture.away_team.id}
        & set(favorite_ids)
        else ""
    )

    if status in LIVE_STATUSES:
        minute = f"{fixture.elapsed}'" if fixture.elapsed else ""
        head = f"🔴 {minute}".strip()
        body = f"{home} {score(fixture)} {away}"
    elif status in BREAK_STATUSES:
        head = f"⏸ {status_label(status, language)}"
        body = f"{home} {score(fixture)} {away}"
    elif status in FINISHED_STATUSES:
        head = f"✅ {status_label(status, language)}"
        body = f"{home} {score(fixture)} {away}"
    elif status in NOT_PLAYED_STATUSES or status == "PST":
        head = f"🚫 {status_label(status, language)}"
        body = f"{home} – {away}"
    elif status == "TBD":
        head = f"🕒 {status_label(status, language)}"
        body = f"{home} – {away}"
    else:
        head = f"🕒 {clock(fixture.start_time, tz)}"
        body = f"{home} – {away}"

    if with_date:
        head = f"{short_date(fixture.start_time, tz)} {head}"

    line = f"{marker}{head} {body}"

    if with_competition and fixture.competition:
        line += f" <i>({escape(fixture.competition)})</i>"

    return line


# --- scope and grouping -----------------------------------------------


def is_top_fixture(fixture: Fixture, favorite_ids: Iterable[int] = ()) -> bool:
    """Whether a match belongs to the bot's fixed editorial coverage.

    Favorite teams are highlighted within this coverage, but do not expand
    the global feed to unrelated leagues.
    """
    return (
        fixture.league_id in featured_competition_ids()
        or fixture.league_country in featured_country_names()
    )


def filter_scope(
    fixtures: Sequence[Fixture],
    scope_is_top: bool,
    favorite_ids: Iterable[int],
) -> list[Fixture]:
    # Keep the parameter for compatibility with older callback payloads.
    # Public live/today feeds are always restricted to editorial coverage.
    return [f for f in fixtures if is_top_fixture(f)]


def _league_header(fixture: Fixture) -> str:
    name = escape(fixture.competition or "")

    if fixture.league_country:
        return f"{name} · {escape(fixture.league_country)}"

    return name


def _group_key(fixture: Fixture) -> tuple:
    return (
        league_priority(fixture.league_id),
        fixture.league_country or "",
        fixture.competition or "",
        fixture.league_id or 0,
    )


def build_match_pages(
    fixtures: Sequence[Fixture],
    *,
    language: str,
    tz: tzinfo,
    favorite_ids: Iterable[int] = (),
    budget: int = PAGE_CHAR_BUDGET,
) -> list[str]:
    """Group matches by competition and split them into message pages.

    Matches of the user's favorite teams come first, in their own
    section. Each match appears once. A page never exceeds ``budget``
    characters, and a competition header is repeated when a competition
    continues on the next page.
    """
    favorites = set(favorite_ids)

    def is_favorite(f: Fixture) -> bool:
        return bool({f.home_team.id, f.away_team.id} & favorites)

    mine = sorted(
        (f for f in fixtures if is_favorite(f)),
        key=lambda f: (f.start_time, f.id),
    )
    others = sorted(
        (f for f in fixtures if not is_favorite(f)),
        key=lambda f: (_group_key(f), f.start_time, f.id),
    )

    units: list[tuple[str, str]] = []
    mine_header = f"<b>{text('my_teams_section', language)}</b>"

    for f in mine:
        units.append(
            (
                mine_header,
                fixture_line(
                    f,
                    language,
                    tz,
                    with_competition=True,
                    favorite_ids=favorites,
                ),
            )
        )

    for f in others:
        units.append(
            (
                f"<b>{_league_header(f)}</b>",
                fixture_line(f, language, tz),
            )
        )

    pages: list[str] = []
    current: list[str] = []
    size = 0
    last_header: str | None = None

    for header, line in units:
        addition = [line]

        if header != last_header:
            addition.insert(0, header)

        added = sum(len(part) + 1 for part in addition)

        if current and size + added > budget:
            pages.append("\n".join(current))
            current, size, last_header = [], 0, None
            addition = [header, line]
            added = sum(len(part) + 1 for part in addition)

        current.extend(addition)
        size += added
        last_header = header

    if current:
        pages.append("\n".join(current))

    return pages


def format_team_upcoming(
    team: Team,
    language: str,
    tz: tzinfo,
    matches: TeamMatches | None,
) -> str:
    lines = [f"📅 <b>{escape(team.name)} — {text('team_upcoming', language)}</b>"]
    if matches is None:
        lines.append(text("fixtures_unavailable", language))
    elif matches.upcoming:
        lines.extend(
            fixture_line(
                fixture, language, tz, with_date=True, with_competition=True
            )
            for fixture in matches.upcoming[:5]
        )
    else:
        lines.append(text("no_upcoming", language))
    return "\\n".join(lines)


# --- footers -----------------------------------------------------------


def freshness_footer(
    fetched_at: float,
    stale: bool,
    *,
    language: str,
    tz: tzinfo,
    tz_name: str,
) -> str:
    moment = datetime.fromtimestamp(fetched_at, tz)
    shown = moment.strftime("%H:%M")
    lines = []

    if stale:
        lines.append(text("stale_notice", language, time=shown))

    lines.append(text("updated_at", language, time=shown, tz=tz_name))

    return "\n".join(lines)


# --- standings -----------------------------------------------------------


def _trim(name: str, width: int = TEAM_NAME_COLUMN) -> str:
    return name if len(name) <= width else name[: width - 1] + "…"


def _table(group: StandingsGroup, language: str) -> str:
    head = (
        f"{'':>2} {text('col_team', language):<{TEAM_NAME_COLUMN}} "
        f"{text('col_played', language):>2} "
        f"{text('col_gd', language):>3} "
        f"{text('col_points', language):>3}"
    )
    rows = [head]

    for row in group.rows:
        rows.append(
            f"{row.rank:>2} {_trim(row.team.name):<{TEAM_NAME_COLUMN}} "
            f"{row.played:>2} {row.goal_diff:>+3} {row.points:>3}"
        )

    return "<pre>" + escape("\n".join(rows)) + "</pre>"


def format_standings(view: LeagueStandings, language: str) -> str:
    league = view.league

    if league is None or not view.groups:
        title = f"<b>{escape(league.name)}</b>\n\n" if league else ""
        return title + text("standings_unavailable", language)

    header = f"🏆 <b>{escape(league.name)}</b>"

    if league.country:
        header += f" · {escape(league.country)}"

    if view.season:
        header += "\n" + text("standings_season", language, season=view.season)

    parts = [header]
    size = len(header)
    shown_groups = 0

    for group in view.groups:
        block = _table(group, language)

        if len(view.groups) > 1 and group.name:
            block = f"<b>{escape(group.name)}</b>\n{block}"

        if size + len(block) > MESSAGE_CHAR_LIMIT and shown_groups:
            parts.append("…")
            break

        parts.append(block)
        size += len(block) + 2
        shown_groups += 1

    return "\n\n".join(parts)


# --- team page -------------------------------------------------------------


def format_team_page(
    team: Team,
    language: str,
    tz: tzinfo,
    matches: TeamMatches | None,
) -> str:
    lines = [f"<b>{escape(team.name)}</b>"]

    if team.country:
        lines.append(
            f"🌍 {text('team_country', language)}: {escape(team.country)}"
        )

    venue = ", ".join(
        escape(part)
        for part in (team.venue_name, team.venue_city)
        if part
    )

    if venue:
        if team.venue_capacity:
            venue += f" ({team.venue_capacity:,})".replace(",", " ")

        lines.append(f"🏟 {text('team_stadium', language)}: {venue}")

    if team.founded:
        lines.append(f"📆 {text('team_founded', language, year=team.founded)}")

    if matches is None:
        lines.append("")
        lines.append(text("fixtures_unavailable", language))
        return "\n".join(lines)

    lines.append("")
    lines.append(f"<b>{text('team_upcoming', language)}</b>")

    if matches.upcoming:
        lines.extend(
            fixture_line(
                f,
                language,
                tz,
                with_date=True,
                with_competition=True,
            )
            for f in matches.upcoming
        )
    else:
        lines.append(text("no_upcoming", language))

    lines.append("")
    lines.append(f"<b>{text('team_recent', language)}</b>")

    if matches.recent:
        lines.extend(
            fixture_line(
                f,
                language,
                tz,
                with_date=True,
                with_competition=True,
            )
            for f in matches.recent
        )
    else:
        lines.append(text("no_recent", language))

    return "\n".join(lines)
