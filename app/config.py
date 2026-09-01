import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_football_key: str
    database_url: str | None
    bot_display_name: str
    default_language: str
    free_favorite_slots: int
    log_level: str


def get_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        api_football_key=os.getenv("API_FOOTBALL_KEY", ""),
        database_url=os.getenv("DATABASE_URL"),
        bot_display_name=os.getenv("BOT_DISPLAY_NAME", "Flash Football"),
        default_language=os.getenv("DEFAULT_LANGUAGE", "uz"),
        free_favorite_slots=int(os.getenv("FREE_FAVORITE_SLOTS", "3")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )