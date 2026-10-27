import asyncio
import logging
from datetime import date, datetime
from typing import Any

import httpx

from app.football.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.football.models import (
    Fixture,
    League,
    MatchEvent,
    SquadPlayer,
    StandingRow,
    StandingsGroup,
    Team,
)
from app.football.provider import FootballProvider

logger = logging.getLogger(__name__)

# Phrases API-Football uses in its ``errors`` object / list.
_QUOTA_HINTS = (
    "request limit",
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
)
_AUTH_HINTS = (
    "application key",
    "api key",
    "apikey",
    "invalid key",
    "token",
    "suspended",
    "subscription",
    "account",
    "not active",
    "unauthorized",
)
_REQUEST_HINTS = (
    "must contain",
    "alphanumeric",
    "at least",
    "characters",
    "required",
    "invalid value",
)

_QUOTA_KEYS = {"requests", "ratelimit", "rate_limit", "limit"}
_AUTH_KEYS = {"token", "key", "apikey", "access", "account"}
_REQUEST_KEYS = {"search", "id", "team", "from", "to", "date"}

_TRANSIENT_STATUSES = {499, 500, 502, 503, 504}


def classify_api_errors(errors: Any) -> ProviderError | None:
    """Turn the ``errors`` field of a response into a typed error.

    API-Football returns HTTP 200 even for failures. ``errors`` is an
    empty list when everything is fine and a non-empty dict (or list)
    otherwise. Returns ``None`` when there is no error.

    The returned exception message is safe to log: it contains only
    the provider's own error text, never request headers or the key.
    """
    if not errors:
        return None

    if isinstance(errors, dict):
        items = [(str(k).lower(), str(v)) for k, v in errors.items()]
    elif isinstance(errors, (list, tuple)):
        items = [("", str(v)) for v in errors]
    else:
        items = [("", str(errors))]

    keys = {key for key, _ in items}
    haystack = " ".join(f"{key} {value}" for key, value in items).lower()
    summary = "; ".join(
        f"{key or 'error'}: {value[:160]}" for key, value in items
    )

    # Quota wording is checked first: some plans report an exhausted
    # daily quota under the "token" key.
    if keys & _QUOTA_KEYS or any(h in haystack for h in _QUOTA_HINTS):
        return ProviderQuotaError(summary)

    if keys & _AUTH_KEYS or any(h in haystack for h in _AUTH_HINTS):
        return ProviderAuthError(summary)

    if keys & _REQUEST_KEYS or any(h in haystack for h in _REQUEST_HINTS):
        return ProviderRequestError(summary)

    return ProviderUnavailableError(summary)


class ApiFootballProvider(FootballProvider):
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(
        self,
        api_key: str,
        timeout: float = 15.0,
        max_retries: int = 1,
        retry_delay: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ):
        # One long-lived client is shared by every request. It is
        # created once at startup and closed on shutdown.
        self.client = client or httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"x-apisports-key": api_key},
            timeout=timeout,
        )
        self.max_retries = max(0, max_retries)
        self.retry_delay = retry_delay
        # Daily quota as last reported by the provider (None = unknown).
        self.requests_remaining: int | None = None
        self.requests_limit: int | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict:
        """GET ``path`` and return the decoded JSON payload.

        Raises a typed ``ProviderError`` for every failure mode.
        Only transient failures (network errors, timeouts, 5xx) are
        retried, at most ``max_retries`` times. Quota, rate-limit and
        authentication failures are never retried, so retries cannot
        multiply API usage.
        """
        attempt = 0

        while True:
            transient: ProviderUnavailableError | None = None

            try:
                response = await self.client.get(path, params=params)
            except httpx.TransportError as exc:
                transient = ProviderUnavailableError(
                    f"{path}: {type(exc).__name__}"
                )
            else:
                status = response.status_code

                if status in (401, 403):
                    raise ProviderAuthError(
                        f"{path}: HTTP {status}"
                    )

                if status == 429:
                    raise ProviderQuotaError(
                        f"{path}: HTTP 429 (rate limited)"
                    )

                if status in _TRANSIENT_STATUSES or status >= 500:
                    transient = ProviderUnavailableError(
                        f"{path}: HTTP {status}"
                    )
                elif status >= 400:
                    raise ProviderRequestError(
                        f"{path}: HTTP {status}"
                    )
                else:
                    self._record_quota(response)
                    return self._decode(path, response)

            if attempt >= self.max_retries:
                raise transient

            attempt += 1
            logger.warning(
                "Transient provider failure (%s); retry %s/%s.",
                transient,
                attempt,
                self.max_retries,
            )
            await asyncio.sleep(self.retry_delay)

    @staticmethod
    def _decode(path: str, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                f"{path}: response was not valid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                f"{path}: unexpected response shape"
            )

        error = classify_api_errors(payload.get("errors"))

        if error is not None:
            raise error

        if not isinstance(payload.get("response", []), list):
            raise ProviderUnavailableError(
                f"{path}: unexpected 'response' shape"
            )

        return payload

    def _record_quota(self, response: httpx.Response) -> None:
        """Remember the daily quota the provider reports, if it does."""
        remaining = _header_int(response, "x-ratelimit-requests-remaining")
        limit = _header_int(response, "x-ratelimit-requests-limit")

        if limit is not None:
            self.requests_limit = limit

        if remaining is None:
            return

        self.requests_remaining = remaining

        if remaining <= LOW_QUOTA_WARNING:
            logger.warning(
                "API-Football daily quota is nearly used up: "
                "%s of %s requests left.",
                remaining,
                self.requests_limit if self.requests_limit else "?",
            )

    async def search_teams(self, query: str) -> list[Team]:
        data = await self._get("/teams", {"search": query})

        return _parse_items(data, _team_from_item, "team")

    async def get_team(self, team_id: int) -> Team | None:
        data = await self._get("/teams", {"id": team_id})
        teams = _parse_items(data, _team_from_item, "team")

        return teams[0] if teams else None

    async def get_team_squad(self, team_id: int) -> list[SquadPlayer]:
        data = await self._get("/players/squads", {"team": team_id})
        players: list[SquadPlayer] = []

        for item in data.get("response", []):
            for raw in item.get("players") or []:
                try:
                    player_id = int(raw["id"])
                    name = str(raw["name"]).strip()
                    if not name:
                        continue
                    players.append(
                        SquadPlayer(
                            id=player_id,
                            name=name,
                            age=_int_or_none(raw.get("age")),
                            number=_int_or_none(raw.get("number")),
                            position=raw.get("position"),
                            photo_url=raw.get("photo"),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    logger.warning("Skipping malformed squad player.")
        return players

    async def get_team_fixtures(
        self,
        team_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Fixture]:
        data = await self._get(
            "/fixtures",
            {
                "team": team_id,
                "from": from_date.date().isoformat(),
                "to": to_date.date().isoformat(),
            },
        )

        return _parse_items(data, _fixture_from_item, "fixture")

    async def get_live_fixtures(self) -> list[Fixture]:
        data = await self._get("/fixtures", {"live": "all"})

        return _parse_items(data, _fixture_from_item, "fixture")

    async def get_fixtures_by_date(
        self,
        day: date,
        timezone: str | None = None,
    ) -> list[Fixture]:
        params: dict[str, Any] = {"date": day.isoformat()}

        if timezone:
            params["timezone"] = timezone

        data = await self._get("/fixtures", params)

        return _parse_items(data, _fixture_from_item, "fixture")

    async def get_leagues(
        self,
        *,
        league_id: int | None = None,
        country: str | None = None,
    ) -> list[League]:
        params: dict[str, Any] = {}

        if league_id is not None:
            params["id"] = league_id

        if country:
            params["country"] = country
            params["current"] = "true"

        if not params:
            raise ValueError("league_id or country is required.")

        data = await self._get("/leagues", params)

        return _parse_items(data, _league_from_item, "league")

    async def get_standings(
        self,
        league_id: int,
        season: int,
    ) -> list[StandingsGroup]:
        data = await self._get(
            "/standings",
            {"league": league_id, "season": season},
        )

        groups: list[StandingsGroup] = []

        for item in data.get("response", []):
            try:
                tables = item["league"]["standings"]
            except (KeyError, TypeError):
                logger.warning("Skipping malformed standings entry.")
                continue

            for table in tables or []:
                rows = []

                for raw in table or []:
                    try:
                        rows.append(_standing_row(raw))
                    except (KeyError, TypeError, ValueError):
                        logger.warning("Skipping malformed standings row.")

                if rows:
                    name = (table[0] or {}).get("group")
                    groups.append(StandingsGroup(name, tuple(rows)))

        return groups

    async def get_live_events(
        self,
        fixture_id: int,
    ) -> list[MatchEvent]:

        data = await self._get("/fixtures", {"id": fixture_id})

        events = []

        for item in data.get("response", []):
            for index, event in enumerate(item.get("events") or []):
                events.append(
                    MatchEvent(
                        fixture_id=fixture_id,
                        event_id=str(
                            event.get("id")
                            or f"{fixture_id}:{index}"
                        ),
                        minute=(event.get("time") or {}).get("elapsed"),
                        event_type=event.get("type", "unknown"),
                        team_id=(event.get("team") or {}).get("id"),
                        player_name=(event.get("player") or {}).get("name"),
                    )
                )

        return events


# --- response parsing -------------------------------------------------

LOW_QUOTA_WARNING = 10


def _header_int(response: httpx.Response, name: str) -> int | None:
    try:
        return int(response.headers.get(name, ""))
    except (TypeError, ValueError):
        return None


def _parse_items(data: dict, parse, label: str) -> list:
    """Parse ``data["response"]``, skipping entries that are malformed.

    One broken entry must not hide the other results, and a missing
    field must never be replaced by invented data.
    """
    parsed = []

    for item in data.get("response", []):
        try:
            result = parse(item)
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.warning("Skipping malformed %s entry.", label)
            continue

        if result is not None:
            parsed.append(result)

    return parsed


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _team_from_item(item: dict) -> Team | None:
    team = (item or {}).get("team") or {}

    if "id" not in team or not team.get("name"):
        return None

    venue = (item or {}).get("venue") or {}

    return Team(
        id=team["id"],
        name=team["name"],
        logo_url=team.get("logo"),
        country=team.get("country"),
        code=team.get("code"),
        national=bool(team.get("national")),
        founded=_int_or_none(team.get("founded")),
        venue_name=venue.get("name"),
        venue_city=venue.get("city"),
        venue_capacity=_int_or_none(venue.get("capacity")),
    )


def _fixture_team(raw: dict) -> Team:
    return Team(
        id=raw["id"],
        name=raw["name"],
        logo_url=raw.get("logo"),
    )


def _fixture_from_item(item: dict) -> Fixture:
    fixture = item["fixture"]
    teams = item["teams"]
    league = item.get("league") or {}
    status = fixture.get("status") or {}
    goals = item.get("goals") or {}

    return Fixture(
        id=fixture["id"],
        home_team=_fixture_team(teams["home"]),
        away_team=_fixture_team(teams["away"]),
        start_time=datetime.fromisoformat(
            fixture["date"].replace("Z", "+00:00")
        ),
        competition=league["name"],
        venue=(fixture.get("venue") or {}).get("name"),
        status=status.get("short") or "NS",
        elapsed=_int_or_none(status.get("elapsed")),
        home_goals=_int_or_none(goals.get("home")),
        away_goals=_int_or_none(goals.get("away")),
        league_id=_int_or_none(league.get("id")),
        league_country=league.get("country"),
    )


def _league_from_item(item: dict) -> League:
    league = item["league"]
    country = (item.get("country") or {}).get("name")
    current = None

    for season in item.get("seasons") or []:
        if season.get("current"):
            current = _int_or_none(season.get("year"))

    return League(
        id=league["id"],
        name=league["name"],
        country=country,
        type=league.get("type"),
        logo_url=league.get("logo"),
        current_season=current,
    )


def _standing_row(raw: dict) -> StandingRow:
    played = raw["all"]

    return StandingRow(
        rank=int(raw["rank"]),
        team=_fixture_team(raw["team"]),
        played=int(played["played"]),
        won=int(played["win"]),
        drawn=int(played["draw"]),
        lost=int(played["lose"]),
        goals_for=int(played["goals"]["for"]),
        goals_against=int(played["goals"]["against"]),
        goal_diff=int(raw["goalsDiff"]),
        points=int(raw["points"]),
        form=raw.get("form"),
    )
