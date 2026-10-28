import httpx
import pytest

from app.football.api_football import (
    ApiFootballProvider,
    classify_api_errors,
)
from app.football.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
)

SECRET_KEY = "super-secret-api-key"


def team_payload(*teams, errors=None):
    return {
        "get": "teams",
        "errors": [] if errors is None else errors,
        "results": len(teams),
        "response": [
            {"team": team, "venue": {}} for team in teams
        ],
    }


BARCA = {
    "id": 529,
    "name": "Barcelona",
    "code": "BAR",
    "country": "Spain",
    "national": False,
    "logo": "https://example.test/barca.png",
}


def make_provider(handler, **kwargs):
    """Provider whose HTTP traffic goes to ``handler`` (no network)."""
    calls = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls))

    client = httpx.AsyncClient(
        base_url=ApiFootballProvider.BASE_URL,
        headers={"x-apisports-key": SECRET_KEY},
        transport=httpx.MockTransport(recording),
    )
    kwargs.setdefault("retry_delay", 0)
    provider = ApiFootballProvider(SECRET_KEY, client=client, **kwargs)
    return provider, calls


async def test_successful_search_is_parsed():
    provider, calls = make_provider(
        lambda r, n: httpx.Response(200, json=team_payload(BARCA))
    )

    teams = await provider.search_teams("barcelona")

    assert [(t.id, t.name, t.country) for t in teams] == [
        (529, "Barcelona", "Spain")
    ]
    assert calls[0].url.params["search"] == "barcelona"
    await provider.close()


async def test_team_squad_endpoint_parses_player_details():
    payload = {
        "errors": [],
        "response": [{
            "team": {"id": 529, "name": "Barcelona"},
            "players": [{
                "id": 10, "name": "Player One", "age": 24,
                "number": 8, "position": "Midfielder",
                "photo": "https://example.test/player.png",
            }],
        }],
    }
    provider, calls = make_provider(
        lambda r, n: httpx.Response(200, json=payload)
    )

    players = await provider.get_team_squad(529)

    assert len(players) == 1
    assert players[0].name == "Player One"
    assert players[0].number == 8
    assert players[0].position == "Midfielder"
    assert calls[0].url.path.endswith("/players/squads")
    await provider.close()


async def test_genuine_no_match_returns_empty_list_not_an_error():
    provider, _ = make_provider(
        lambda r, n: httpx.Response(200, json=team_payload())
    )

    assert await provider.search_teams("zzzzzz") == []


async def test_malformed_team_entries_are_skipped_not_invented():
    provider, _ = make_provider(
        lambda r, n: httpx.Response(
            200,
            json=team_payload({"name": "No Id FC"}, BARCA, {"id": 5}),
        )
    )

    teams = await provider.search_teams("barcelona")

    assert [t.id for t in teams] == [529]


# --- HTTP 200 carrying an errors object -------------------------------------


@pytest.mark.parametrize(
    "errors, expected",
    [
        (
            {"token": "Error/Missing application key. Go to ..."},
            ProviderAuthError,
        ),
        (
            {"requests": "You have reached the request limit for the day"},
            ProviderQuotaError,
        ),
        (
            {"rateLimit": "Too many requests. Your rate limit is 10 "
                          "requests per minute."},
            ProviderQuotaError,
        ),
        (
            # Quota exhaustion reported under the "token" key.
            {"token": "You have reached the request limit for the day"},
            ProviderQuotaError,
        ),
        (
            {"search": "The Search field must contain at least 3 "
                       "characters."},
            ProviderRequestError,
        ),
        ({"bug": "Something went wrong"}, ProviderUnavailableError),
        (["Some list style error"], ProviderUnavailableError),
    ],
)
async def test_http_200_with_populated_errors_field(errors, expected):
    provider, calls = make_provider(
        lambda r, n: httpx.Response(
            200, json=team_payload(errors=errors)
        )
    )

    with pytest.raises(expected):
        await provider.search_teams("barcelona")

    # Never retried: a retry cannot fix quota/auth/request problems.
    assert len(calls) == 1


def test_empty_errors_values_mean_success():
    assert classify_api_errors([]) is None
    assert classify_api_errors({}) is None
    assert classify_api_errors(None) is None


# --- HTTP status handling ----------------------------------------------------


async def test_http_429_is_quota_and_not_retried():
    provider, calls = make_provider(
        lambda r, n: httpx.Response(429, json={}), max_retries=3
    )

    with pytest.raises(ProviderQuotaError):
        await provider.search_teams("barcelona")

    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403])
async def test_http_401_403_are_auth_errors_and_not_retried(status):
    provider, calls = make_provider(
        lambda r, n: httpx.Response(status), max_retries=3
    )

    with pytest.raises(ProviderAuthError):
        await provider.search_teams("barcelona")

    assert len(calls) == 1


async def test_transient_5xx_is_retried_once_then_succeeds():
    def handler(request, n):
        if n == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=team_payload(BARCA))

    provider, calls = make_provider(handler)

    teams = await provider.search_teams("barcelona")

    assert len(teams) == 1
    assert len(calls) == 2


async def test_persistent_5xx_gives_up_after_bounded_retries():
    provider, calls = make_provider(
        lambda r, n: httpx.Response(500), max_retries=1
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")

    assert len(calls) == 2  # first attempt + exactly one retry


async def test_retries_can_be_disabled():
    provider, calls = make_provider(
        lambda r, n: httpx.Response(500), max_retries=0
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")

    assert len(calls) == 1


async def test_timeout_is_a_temporary_failure_with_bounded_retry():
    def handler(request, n):
        raise httpx.ReadTimeout("slow", request=request)

    provider, calls = make_provider(handler, max_retries=1)

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")

    assert len(calls) == 2


async def test_connection_error_is_a_temporary_failure():
    def handler(request, n):
        raise httpx.ConnectError("down", request=request)

    provider, _ = make_provider(handler, max_retries=0)

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")


async def test_non_json_body_is_a_temporary_failure():
    provider, _ = make_provider(
        lambda r, n: httpx.Response(200, text="<html>oops</html>")
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")


async def test_unexpected_json_shape_is_a_temporary_failure():
    provider, _ = make_provider(
        lambda r, n: httpx.Response(200, json=["not", "a", "dict"])
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.search_teams("barcelona")


async def test_other_4xx_is_a_request_error():
    provider, _ = make_provider(lambda r, n: httpx.Response(404))

    with pytest.raises(ProviderRequestError):
        await provider.search_teams("barcelona")


async def test_error_messages_never_contain_the_api_key():
    for response in (
        httpx.Response(401),
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(200, json=team_payload(errors={"token": "bad"})),
    ):
        provider, _ = make_provider(
            lambda r, n, resp=response: resp, max_retries=0
        )

        with pytest.raises(Exception) as raised:
            await provider.search_teams("barcelona")

        assert SECRET_KEY not in str(raised.value)
        assert SECRET_KEY not in repr(raised.value)


async def test_single_client_is_reused_across_requests():
    provider, calls = make_provider(
        lambda r, n: httpx.Response(200, json=team_payload(BARCA))
    )
    client = provider.client

    await provider.search_teams("barcelona")
    await provider.search_teams("liverpool")

    assert provider.client is client
    assert len(calls) == 2
