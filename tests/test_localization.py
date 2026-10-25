import string

from app.localization.i18n import (
    SUPPORTED_LANGUAGES,
    TEXTS,
    normalize_language,
    text,
)


def test_uzbek_welcome():
    assert "Flash Football" in text("welcome", "uz")


def test_unknown_language_falls_back_to_uzbek():
    assert text("welcome", "xx") == text("welcome", "uz")


def test_every_language_has_exactly_the_same_keys():
    reference = set(TEXTS["uz"])

    for language in SUPPORTED_LANGUAGES:
        assert set(TEXTS[language]) == reference, language


def test_placeholders_match_across_languages():
    formatter = string.Formatter()

    def fields(value):
        return {f for _, f, _, _ in formatter.parse(value) if f}

    for key in TEXTS["uz"]:
        expected = fields(TEXTS["uz"][key])

        for language in SUPPORTED_LANGUAGES:
            assert fields(TEXTS[language][key]) == expected, (key, language)


def test_limit_message_is_formatted_with_the_configured_number():
    for language in SUPPORTED_LANGUAGES:
        assert "7" in text("team_limit", language, limit=7)
        assert "{" not in text("team_limit", language, limit=7)


def test_missing_key_returns_the_key_itself():
    assert text("does_not_exist", "en") == "does_not_exist"


def test_normalize_language():
    assert normalize_language("ru") == "ru"
    assert normalize_language("xx") == "uz"
    assert normalize_language(None) == "uz"
    assert normalize_language("xx", default="en") == "en"
    assert normalize_language("xx", default="zz") == "uz"
