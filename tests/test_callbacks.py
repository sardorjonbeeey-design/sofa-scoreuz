import pytest

from app.bot.callbacks import (
    ACTION_ADD_TEAM,
    ACTION_REMOVE_TEAM,
    TELEGRAM_CALLBACK_MAX_BYTES,
    ensure_callback_size,
    is_legacy_add_callback,
    parse_team_callback,
    team_callback,
)
from app.bot.handlers.start import language_keyboard
from app.bot.handlers.menu import main_menu
from app.bot.handlers.teams import (
    my_teams_keyboard,
    teams_keyboard,
)
from app.football.team_resolver import display_name
from app.storage.store import FavoriteTeamRecord
from tests.conftest import make_team

CYRILLIC_NAMES = [
    "Манчестер Юнайтед Футбольный Клуб Академия",
    "Бавария Мюнхен — молодёжная команда до 21 года",
    "Зенит Санкт-Петербург Женский Футбольный Клуб",
]


def all_callback_data(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_payloads_are_compact_and_roundtrip():
    data = team_callback(ACTION_ADD_TEAM, 33)

    assert data == "team:add:33"
    assert parse_team_callback(data, ACTION_ADD_TEAM) == 33
    assert parse_team_callback(
        team_callback(ACTION_REMOVE_TEAM, 7), ACTION_REMOVE_TEAM
    ) == 7


def test_largest_possible_payload_fits_in_64_bytes():
    data = team_callback(ACTION_ADD_TEAM, 999_999_999_999)

    assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_MAX_BYTES


def test_search_result_buttons_stay_within_64_bytes_for_cyrillic():
    teams = [
        make_team(10_000 + i, name, country="Russia")
        for i, name in enumerate(CYRILLIC_NAMES)
    ]

    markup = teams_keyboard(teams, "ru")

    for data in all_callback_data(markup):
        assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_MAX_BYTES

    # Names must never travel inside callback data.
    for data in all_callback_data(markup):
        for name in CYRILLIC_NAMES:
            assert name[:5] not in data


def test_my_teams_buttons_stay_within_64_bytes_for_cyrillic():
    favorites = [
        FavoriteTeamRecord(900_000_000 + i, name)
        for i, name in enumerate(CYRILLIC_NAMES)
    ]

    markup = my_teams_keyboard("ru", favorites)

    for data in all_callback_data(markup):
        assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_MAX_BYTES


def test_static_menus_stay_within_64_bytes():
    for markup in (language_keyboard(), main_menu("uz"),
                   main_menu("ru"), main_menu("en")):
        for data in all_callback_data(markup):
            assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_MAX_BYTES


def test_size_check_counts_bytes_not_characters():
    # 40 Cyrillic characters = 80 bytes: under 64 chars, over 64 bytes.
    cyrillic = "я" * 40

    assert len(cyrillic) < 64
    with pytest.raises(ValueError):
        ensure_callback_size(cyrillic)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "team:add:",
        "team:add:abc",
        "team:add:0",
        "team:add:-5",
        "team:add:007x",
        "team:add:12:Barcelona",
        "team:add:1234567890123",          # too many digits
        "team:add:٣٣",                     # non-ASCII digits
        "team:add:33\n",
        "team:rm:33",                      # wrong action for this parser
        "other:add:33",
        "team:add:33:extra:parts",
    ],
)
def test_malformed_payloads_are_rejected(bad):
    assert parse_team_callback(bad, ACTION_ADD_TEAM) is None


def test_builder_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        team_callback("unknown", 1)

    with pytest.raises(ValueError):
        team_callback(ACTION_ADD_TEAM, 0)


def test_legacy_buttons_from_older_versions_are_recognised():
    assert is_legacy_add_callback("team:add:33:Barcelona")
    assert not is_legacy_add_callback("team:add:33")
    assert not is_legacy_add_callback(None)


def test_team_disambiguation_label_is_deterministic():
    team = make_team(1, "Barcelona", country="Spain", code="BAR")

    labels = {display_name(team) for _ in range(200)}

    assert labels == {"Barcelona 🇪🇸 Spain"}
