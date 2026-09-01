TEXTS = {
    "uz": {
        "choose_language": "🌐 Tilni tanlang:",
        "welcome": (
            "⚽ <b>Flash Football</b> ga xush kelibsiz!\n\n"
            "Sevimli jamoalaringizni tanlang va ularning "
            "o‘yinlari, yangiliklari va statistikalarini kuzating."
        ),
        "my_teams": "⭐ Sevimli jamoalarim",
        "matches": "📅 Bo‘lajak o‘yinlar",
        "news": "📰 Yangiliklar",
        "standings": "📊 Turnir jadvallari",
        "settings": "⚙️ Sozlamalar",
        "coming_soon": "🚧 Bu bo‘lim tez orada ishga tushadi.",
        "language_saved": "✅ Til saqlandi.",
    },
    "ru": {
        "choose_language": "🌐 Выберите язык:",
        "welcome": (
            "⚽ Добро пожаловать в <b>Flash Football</b>!\n\n"
            "Выберите любимые команды и следите за матчами, "
            "новостями и статистикой."
        ),
        "my_teams": "⭐ Мои команды",
        "matches": "📅 Предстоящие матчи",
        "news": "📰 Новости",
        "standings": "📊 Турнирные таблицы",
        "settings": "⚙️ Настройки",
        "coming_soon": "🚧 Этот раздел скоро будет доступен.",
        "language_saved": "✅ Язык сохранён.",
    },
    "en": {
        "choose_language": "🌐 Choose your language:",
        "welcome": (
            "⚽ Welcome to <b>Flash Football</b>!\n\n"
            "Choose your favorite teams and follow their "
            "matches, news and statistics."
        ),
        "my_teams": "⭐ My Teams",
        "matches": "📅 Upcoming Matches",
        "news": "📰 News",
        "standings": "📊 Standings",
        "settings": "⚙️ Settings",
        "coming_soon": "🚧 This section is coming soon.",
        "language_saved": "✅ Language saved.",
    },
}


def text(key: str, language: str = "uz") -> str:
    return TEXTS.get(language, TEXTS["uz"]).get(key, key)