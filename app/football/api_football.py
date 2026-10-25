import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from app.football.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.football.models import Fixture, MatchEvent, Team
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

    async def search_teams(self, query: str) -> list[Team]:
        data = await self._get("/teams", {"search": query})

        teams: list[Team] = []

        for item in data.get("response", []):
            team = (item or {}).get("team") or {}

            if "id" not in team or not team.get("name"):
                logger.warning("Skipping malformed team entry.")
                continue

            teams.append(
                Team(
                    id=team["id"],
                    name=team["name"],
                    logo_url=team.get("logo"),
                    country=team.get("country"),
                    code=team.get("code"),
                    national=bool(team.get("national")),
                )
            )

        return teams

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

        fixtures = []

        for item in data.get("response", []):
            fixture = item["fixture"]
            teams = item["teams"]

            fixtures.append(
                Fixture(
                    id=fixture["id"],
                    home_team=Team(
                        id=teams["home"]["id"],
                        name=teams["home"]["name"],
                        logo_url=teams["home"].get("logo"),
                    ),
                    away_team=Team(
                        id=teams["away"]["id"],
                        name=teams["away"]["name"],
                        logo_url=teams["away"].get("logo"),
                    ),
                    start_time=datetime.fromisoformat(
                        fixture["date"].replace("Z", "+00:00")
                    ),
                    competition=item["league"]["name"],
                    venue=(fixture.get("venue") or {}).get("name"),
                )
            )

        return fixtures

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
