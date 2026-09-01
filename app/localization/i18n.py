TEXTS = {
    "uz": {
        "welcome": (
            "⚽ <b>Flash Football</b> ga xush kelibsiz!\n\n"
            "Sevimli jamoalaringizni tanlang va ularning "
            "o‘yinlari, yangiliklari va statistikalarini kuzating."
        ),
    },
    "ru": {
        "welcome": (
            "⚽ Добро пожаловать в <b>Flash Football</b>!\n\n"
            "Выберите любимые команды и следите за матчами, "
            "новостями и статистикой."
        ),
    },
    "en": {
        "welcome": (
            "⚽ Welcome to <b>Flash Football</b>!\n\n"
            "Choose your favorite teams and follow their "
            "matches, news and statistics."
        ),
    },
}


def text(key: str, language: str = "uz") -> str:
    return TEXTS.get(language, TEXTS["uz"]).get(key, key)