import logging

from aiogram.exceptions import TelegramBadRequest

from app.config import Settings
from app.football.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
)
from app.localization.i18n import normalize_language
from app.storage.database import StorageError
from app.storage.store import PreferenceStore

logger = logging.getLogger(__name__)


async def user_language(
    store: PreferenceStore,
    settings: Settings,
    telegram_id: int,
) -> str:
    """The user's saved language, or the configured default.

    A storage failure must not break the interface: it falls back to
    the default language and is logged by the store.
    """
    default = normalize_language(settings.default_language)

    try:
        saved = await store.get_language(telegram_id)
    except StorageError:
        return default

    return normalize_language(saved, default)


async def edit_or_answer(
    callback,
    message_text: str,
    reply_markup=None,
) -> None:
    """Edit the message holding the pressed button.

    Falls back to sending a new message when the original message is
    no longer editable (too old / inaccessible). "Message is not
    modified" is not an error.
    """
    message = callback.message
    edit = getattr(message, "edit_text", None)

    if edit is not None:
        try:
            await edit(message_text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return

            logger.info("Could not edit message: %s", exc)

    answer = getattr(message, "answer", None)

    if answer is not None:
        await answer(message_text, reply_markup=reply_markup)


def provider_error_key(error: ProviderError) -> str:
    """Localization key for a provider failure (never leaks details)."""
    if isinstance(error, ProviderQuotaError):
        return "provider_quota"

    if isinstance(error, ProviderAuthError):
        return "provider_auth"

    return "provider_unavailable"


async def favorite_team_ids(
    store: PreferenceStore,
    telegram_id: int,
) -> set[int]:
    """Ids of the user's favorite teams.

    Used only to highlight matches, so a storage failure degrades to
    "no highlights" instead of breaking the screen. The store has
    already logged the failure.
    """
    try:
        favorites = await store.list_favorites(telegram_id)
    except StorageError:
        return set()

    return {favorite.team_id for favorite in favorites}
