"""Compact, validated callback payloads.

Telegram rejects callback data longer than 64 BYTES (not characters),
so payloads carry only an action and a numeric id. Display text such as
team names never travels inside callback data.
"""

import re

TELEGRAM_CALLBACK_MAX_BYTES = 64

ACTION_ADD_TEAM = "add"
ACTION_REMOVE_TEAM = "rm"
ACTION_VIEW_TEAM = "view"

TEAM_ACTIONS = (ACTION_ADD_TEAM, ACTION_REMOVE_TEAM, ACTION_VIEW_TEAM)

# Strict: ASCII digits only (``\d`` would also accept other scripts),
# positive ids, bounded length.
_TEAM_CALLBACK = re.compile(r"team:(add|rm|view):([1-9][0-9]{0,11})")

# Buttons sent by older versions looked like "team:add:<id>:<name>".
_LEGACY_ADD_CALLBACK = re.compile(r"team:add:[0-9]+:.*", re.DOTALL)


def ensure_callback_size(data: str) -> str:
    if len(data.encode("utf-8")) > TELEGRAM_CALLBACK_MAX_BYTES:
        raise ValueError(
            "Callback data exceeds Telegram's "
            f"{TELEGRAM_CALLBACK_MAX_BYTES}-byte limit."
        )

    return data


def team_callback(action: str, team_id: int) -> str:
    if action not in TEAM_ACTIONS:
        raise ValueError(f"Unknown team action: {action!r}")

    if not isinstance(team_id, int) or team_id < 1:
        raise ValueError("team_id must be a positive integer.")

    return ensure_callback_size(f"team:{action}:{team_id}")


def parse_team_callback(
    data: str | None,
    action: str,
) -> int | None:
    """Return the team id, or ``None`` for anything malformed."""
    if not data:
        return None

    match = _TEAM_CALLBACK.fullmatch(data)

    if match is None or match.group(1) != action:
        return None

    return int(match.group(2))


def is_legacy_add_callback(data: str | None) -> bool:
    return bool(data) and _LEGACY_ADD_CALLBACK.fullmatch(data) is not None


# --- match lists (live / today) ----------------------------------------

KIND_LIVE = "l"
KIND_TODAY = "d"
SCOPE_TOP = "t"
SCOPE_ALL = "a"

MAX_PAGE = 999

_FIXTURES_CALLBACK = re.compile(r"fx:([ld]):([ta]):([0-9]{1,3})")


def fixtures_callback(kind: str, scope: str, page: int = 0) -> str:
    if kind not in (KIND_LIVE, KIND_TODAY):
        raise ValueError(f"Unknown fixtures kind: {kind!r}")

    if scope not in (SCOPE_TOP, SCOPE_ALL):
        raise ValueError(f"Unknown fixtures scope: {scope!r}")

    if not isinstance(page, int) or not 0 <= page <= MAX_PAGE:
        raise ValueError("page is out of range.")

    return ensure_callback_size(f"fx:{kind}:{scope}:{page}")


def parse_fixtures_callback(
    data: str | None,
) -> tuple[str, str, int] | None:
    """Return ``(kind, scope, page)``, or ``None`` if malformed."""
    if not data:
        return None

    match = _FIXTURES_CALLBACK.fullmatch(data)

    if match is None:
        return None

    return match.group(1), match.group(2), int(match.group(3))


# --- leagues -----------------------------------------------------------

_LEAGUE_CALLBACK = re.compile(r"lg:([1-9][0-9]{0,8})")
_COUNTRY_CALLBACK = re.compile(r"lgc:([A-Z]{2})")


def league_callback(league_id: int) -> str:
    if not isinstance(league_id, int) or league_id < 1:
        raise ValueError("league_id must be a positive integer.")

    return ensure_callback_size(f"lg:{league_id}")


def parse_league_callback(data: str | None) -> int | None:
    if not data:
        return None

    match = _LEAGUE_CALLBACK.fullmatch(data)

    return int(match.group(1)) if match else None


def country_callback(code: str) -> str:
    if not _COUNTRY_CALLBACK.fullmatch(f"lgc:{code}"):
        raise ValueError("country code must be two capital letters.")

    return ensure_callback_size(f"lgc:{code}")


def parse_country_callback(data: str | None) -> str | None:
    if not data:
        return None

    match = _COUNTRY_CALLBACK.fullmatch(data)

    return match.group(1) if match else None
