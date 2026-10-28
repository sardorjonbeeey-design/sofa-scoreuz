"""Typed errors raised by football data providers.

The bot layer maps these to short, localized user messages. Detailed
diagnostics belong in logs and must never include credentials.
"""


class ProviderError(Exception):
    """Base class for every provider failure."""


class ProviderAuthError(ProviderError):
    """Invalid, missing or suspended credentials / subscription."""


class ProviderQuotaError(ProviderError):
    """Daily quota exhausted or per-minute rate limit hit."""


class ProviderUnavailableError(ProviderError):
    """Timeouts, network failures, 5xx or unusable responses."""


class ProviderRequestError(ProviderError):
    """The provider rejected the request parameters themselves.

    Example: a search string that is too short. This is a problem with
    the query, not an outage, and must not be reported as one.
    """
