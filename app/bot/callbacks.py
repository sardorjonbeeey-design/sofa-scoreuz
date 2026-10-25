"""Compact, validated callback payloads.

Telegram rejects callback data longer than 64 BYTES (not characters),
so payloads carry only an action and a numeric id. Display text such as
team names never travels inside callback data.
"""

import re

TELEGRAM_CALLBACK_MAX_BYTES = 64

ACTION_ADD_TEAM = "add"
ACTION_REMOVE_TEAM = "rm"

# Strict: ASCII digits only (``\d`` would also accept other scripts),
# positive ids, bounded length.
_TEAM_CALLBACK = re.compile(r"team:(add|rm):([1-9][0-9]{0,11})")

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
    if action not in (ACTION_ADD_TEAM, ACTION_REMOVE_TEAM):
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
