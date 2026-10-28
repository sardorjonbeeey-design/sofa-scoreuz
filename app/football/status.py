"""Match status codes used by API-Football (``fixture.status.short``)."""

# In play: the clock is running (or the match is on a short break).
LIVE_STATUSES = frozenset({"1H", "2H", "ET", "BT", "P", "LIVE"})
BREAK_STATUSES = frozenset({"HT", "INT", "SUSP"})
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN", "AWD", "WO"})
NOT_PLAYED_STATUSES = frozenset({"CANC", "ABD"})
SCHEDULED_STATUSES = frozenset({"NS", "TBD", "PST"})

ALL_KNOWN = (
    LIVE_STATUSES
    | BREAK_STATUSES
    | FINISHED_STATUSES
    | NOT_PLAYED_STATUSES
    | SCHEDULED_STATUSES
)


def is_live(status: str) -> bool:
    return status in LIVE_STATUSES or status in BREAK_STATUSES


def is_finished(status: str) -> bool:
    return status in FINISHED_STATUSES


def has_score(status: str) -> bool:
    return is_live(status) or is_finished(status)
