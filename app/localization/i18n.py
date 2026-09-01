TEXTS = {
    "uz": {
        "welcome": (
            "⚽ <b>Flash Football</b> ga xush kelibsiz!\n\n"
            "Sevimli jamoalaringizni tanlang va ularning "
            "o‘yinlari, yangiliklari va statistikalarini kuzating."
        ),
        "choose_language": "🌐 Tilni tanlang:",
        "language_saved": "Til saqlandi.",
        "my_teams": "⭐ Mening jamoalarim",
        "matches": "📅 O‘yinlar",
        "news": "📰 Yangiliklar",
        "standings": "🏆 Turnir jadvali",
        "settings": "⚙️ Sozlamalar",
        "add_team": "➕ Jamoa qo‘shish",
        "back": "⬅️ Orqaga",
        "no_teams": "Sizda hali sevimli jamoalar yo‘q.",
        "send_team_name": "🔎 Jamoa nomini yozing:",
        "team_search_results": "🔎 Topilgan jamoalar:",
        "team_added": "✅ Jamoa sevimlilaringizga qo‘shildi!",
        "team_already_added": "ℹ️ Bu jamoa allaqachon qo‘shilgan.",
        "team_limit": "⚠️ Siz maksimal 3 ta sevimli jamoa qo‘sha olasiz.",
        "no_teams_found": "❌ Jamoa topilmadi. Boshqa nom bilan urinib ko‘ring.",
        "coming_soon": "🚧 Bu bo‘lim tez orada ishga tushadi.",
    },

    "ru": {
        "welcome": (
            "⚽ Добро пожаловать в <b>Flash Football</b>!\n\n"
            "Выберите любимые команды и следите за матчами, "
            "новостями и статистикой."
        ),
        "choose_language": "🌐 Выберите язык:",
        "language_saved": "Язык сохранён.",
        "my_teams": "⭐ Мои команды",
        "matches": "📅 Матчи",
        "news": "📰 Новости",
        "standings": "🏆 Турнирная таблица",
        "settings": "⚙️ Настройки",
        "add_team": "➕ Добавить команду",
        "back": "⬅️ Назад",
        "no_teams": "У вас пока нет любимых команд.",
        "send_team_name": "🔎 Напишите название команды:",
        "team_search_results": "🔎 Найденные команды:",
        "team_added": "✅ Команда добавлена в избранное!",
        "team_already_added": "ℹ️ Эта команда уже добавлена.",
        "team_limit": "⚠️ Можно добавить максимум 3 любимые команды.",
        "no_teams_found": "❌ Команда не найдена. Попробуйте другое название.",
        "coming_soon": "🚧 Этот раздел скоро будет доступен.",
    },

    "en": {
        "welcome": (
            "⚽ Welcome to <b>Flash Football</b>!\n\n"
            "Choose your favorite teams and follow their "
            "matches, news and statistics."
        ),
        "choose_language": "🌐 Choose your language:",
        "language_saved": "Language saved.",
        "my_teams": "⭐ My Teams",
        "matches": "📅 Matches",
        "news": "📰 News",
        "standings": "🏆 Standings",
        "settings": "⚙️ Settings",
        "add_team": "➕ Add Team",
        "back": "⬅️ Back",
        "no_teams": "You don't have any favorite teams yet.",
        "send_team_name": "🔎 Enter a team name:",
        "team_search_results": "🔎 Teams found:",
        "team_added": "✅ Team added to your favorites!",
        "team_already_added": "ℹ️ This team is already added.",
        "team_limit": "⚠️ You can add a maximum of 3 favorite teams.",
        "no_teams_found": "❌ Team not found. Try another name.",
        "coming_soon": "🚧 This section is coming soon.",
    },
}


def text(key: str, language: str = "uz") -> str:
    language_texts = TEXTS.get(language, TEXTS["uz"])
    return language_texts.get(key, TEXTS["uz"].get(key, key))