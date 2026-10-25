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


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    )
