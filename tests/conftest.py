from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.football.models import Team


def make_settings(**overrides) -> Settings:
    values = dict(
        bot_token="123456:TEST-TOKEN",
        api_football_key="test-key",
        database_url=None,
        bot_display_name="Flash Football",
        default_language="uz",
        free_favorite_slots=3,
        log_level="INFO",
        require_database=False,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


def make_callback(data: str, user_id: int = 42):
    """Minimal stand-in for aiogram's CallbackQuery."""
    message = SimpleNamespace(
        edit_text=AsyncMock(),
        answer=AsyncMock(),
    )
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=message,
        answer=AsyncMock(),
    )


def make_message(text: str | None, user_id: int = 42):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def make_team(team_id: int, name: str, **kwargs) -> Team:
    return Team(id=team_id, name=name, **kwargs)
