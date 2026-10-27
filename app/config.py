import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_football_key: str
    database_url: str | None
    bot_display_name: str
    default_language: str
    free_favorite_slots: int
    log_level: str
    require_database: bool = False
    # Timezone used to decide what "today" is and to show kickoff times.
    display_timezone: str = "Asia/Tashkent"
    # How long (seconds) live scores / fixture lists are shared between
    # users before the provider is asked again.
    live_cache_ttl: int = 60
    fixtures_cache_ttl: int = 300
    supporter_bot_token: str = ""
    archive_channel_id: int | None = None
    tinyfish_api_key: str = ""
    archive_foundation_interval_seconds: int = 86400
    archive_foundation_republish_cached: bool = False


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Environment variable %s is not a valid integer; "
            "using default %s.",
            name,
            default,
        )
        return default


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)

    if value < 1:
        logger.warning(
            "Environment variable %s must be at least 1; using %s.",
            name,
            default,
        )
        return default

    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Environment variable %s is not a valid integer; archive publishing is disabled.", name)
        return None


def get_settings() -> Settings:
    # Empty values (for example "DATABASE_URL=" copied from
    # .env.example) are treated the same as "not set".
    database_url = (os.getenv("DATABASE_URL") or "").strip() or None

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        api_football_key=os.getenv("API_FOOTBALL_KEY", "").strip(),
        database_url=database_url,
        bot_display_name=os.getenv("BOT_DISPLAY_NAME", "Flash Football"),
        default_language=os.getenv("DEFAULT_LANGUAGE", "uz"),
        free_favorite_slots=_int_env("FREE_FAVORITE_SLOTS", 3),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        require_database=_bool_env("REQUIRE_DATABASE", False),
        display_timezone=(
            os.getenv("DISPLAY_TIMEZONE", "").strip() or "Asia/Tashkent"
        ),
        live_cache_ttl=_positive_int_env("LIVE_CACHE_TTL_SECONDS", 60),
        fixtures_cache_ttl=_positive_int_env(
            "FIXTURES_CACHE_TTL_SECONDS", 300
        ),
        supporter_bot_token=os.getenv("SUPPORTER_BOT_TOKEN", "").strip(),
        archive_channel_id=_optional_int_env("ARCHIVE_CHANNEL_ID"),
        tinyfish_api_key=os.getenv("TINYFISH_API_KEY", "").strip(),
        archive_foundation_interval_seconds=_positive_int_env(
            "ARCHIVE_FOUNDATION_INTERVAL_SECONDS", 86400
        ),
        archive_foundation_republish_cached=_bool_env(
            "ARCHIVE_FOUNDATION_REPUBLISH_CACHED", False
        ),
    )
