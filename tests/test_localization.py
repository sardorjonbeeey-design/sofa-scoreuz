from app.localization.i18n import text


def test_uzbek_welcome():
    assert "Flash Football" in text("welcome", "uz")


def test_unknown_language_falls_back_to_uzbek():
    assert text("welcome", "xx") == text("welcome", "uz")