"""Texts for the football features (live, today, standings, team pages).

Merged into ``TEXTS`` by ``app.localization.i18n``, so the parity tests
(same keys and placeholders in every language) cover them too.
League, team and country names come from the data provider and are
shown as returned.
"""

FOOTBALL_TEXTS = {
    "uz": {
        # main menu
        "live": "🔴 Jonli o‘yinlar",
        "today": "📅 Bugungi o‘yinlar",
        "find_team": "🔎 Jamoa qidirish",
        # live / today
        "live_title": "🔴 <b>Jonli o‘yinlar</b>",
        "today_title": "📅 <b>Bugungi o‘yinlar</b> — {date}",
        "scope_top": "⭐ Top ligalar",
        "scope_all": "🌍 Barcha o‘yinlar",
        "refresh": "🔄 Yangilash",
        "no_live": "Hozir jonli o‘yinlar yo‘q.",
        "no_today": "Bugun o‘yinlar topilmadi.",
        "no_top_matches": (
            "Tanlangan asosiy ligalar va turnirlarda hozircha o‘yin yo‘q."
        ),
        "updated_at": "🕒 Yangilandi: {time} ({tz})",
        "stale_notice": (
            "⚠️ Ma’lumotni yangilab bo‘lmadi. Oxirgi yangilanish: {time}."
        ),
        "my_teams_section": "⭐ Mening jamoalarim",
        # standings
        "standings_pick": "🏆 Chempionatni tanlang:",
        "country_leagues_title": "{flag} <b>{country}</b> chempionatlari:",
        "no_country_leagues": "Bu mamlakat uchun chempionatlar topilmadi.",
        "standings_unavailable": (
            "Bu chempionat uchun jadval hozircha mavjud emas."
        ),
        "standings_season": "Mavsum {season}",
        "col_team": "Jamoa",
        "col_played": "O‘",
        "col_gd": "TF",
        "col_points": "Och",
        # team page
        "team_country": "Mamlakat",
        "team_stadium": "Stadion",
        "team_founded": "Asos solingan yil: {year}",
        "team_upcoming": "📅 Yaqin o‘yinlar",
        "team_recent": "🕘 So‘nggi natijalar",
        "no_upcoming": "Yaqin o‘yinlar topilmadi.",
        "no_recent": "So‘nggi natijalar topilmadi.",
        "fixtures_unavailable": (
            "O‘yinlar ro‘yxatini hozir yuklab bo‘lmadi."
        ),
        "add_to_favorites": "⭐ Sevimlilarga qo‘shish",
        "remove_from_favorites": "🗑 Sevimlilardan olib tashlash",
        "team_page_unavailable": (
            "Jamoa ma’lumotlarini hozir yuklab bo‘lmadi."
        ),
        # unfinished / settings
        "news_unavailable": (
            "📰 <b>Yangiliklar</b>\n\n🚧 Bu bo‘lim hali tayyor emas. "
            "Hozircha yangiliklar mavjud emas."
        ),
        "settings_title": "⚙️ <b>Sozlamalar</b>\n\nTilni tanlang:",
        "settings_timezone": "🕒 Vaqt zonasi: {tz}",
        # match status labels
        "status_HT": "Tanaffus",
        "status_FT": "Tugadi",
        "status_AET": "Q.v.",
        "status_PEN": "Penalti",
        "status_AWD": "Texnik",
        "status_WO": "Texnik",
        "status_PST": "Qoldirildi",
        "status_CANC": "Bekor qilindi",
        "status_ABD": "To‘xtatildi",
        "status_SUSP": "To‘xtatildi",
        "status_INT": "Tanaffus",
        "status_TBD": "Vaqti aniqlanmagan",
        "status_LIVE": "Jonli",
    },
    "ru": {
        "live": "🔴 Матчи Live",
        "today": "📅 Матчи сегодня",
        "find_team": "🔎 Поиск команды",
        "live_title": "🔴 <b>Матчи в прямом эфире</b>",
        "today_title": "📅 <b>Матчи сегодня</b> — {date}",
        "scope_top": "⭐ Топ-лиги",
        "scope_all": "🌍 Все матчи",
        "refresh": "🔄 Обновить",
        "no_live": "Сейчас нет матчей в прямом эфире.",
        "no_today": "Сегодня матчей не найдено.",
        "no_top_matches": (
            "В выбранных основных лигах и турнирах сейчас нет матчей."
        ),
        "updated_at": "🕒 Обновлено: {time} ({tz})",
        "stale_notice": (
            "⚠️ Не удалось обновить данные. "
            "Последнее обновление: {time}."
        ),
        "my_teams_section": "⭐ Мои команды",
        "standings_pick": "🏆 Выберите чемпионат:",
        "country_leagues_title": "{flag} <b>{country}</b> — чемпионаты:",
        "no_country_leagues": "Для этой страны чемпионаты не найдены.",
        "standings_unavailable": (
            "Таблица для этого чемпионата пока недоступна."
        ),
        "standings_season": "Сезон {season}",
        "col_team": "Команда",
        "col_played": "И",
        "col_gd": "РМ",
        "col_points": "О",
        "team_country": "Страна",
        "team_stadium": "Стадион",
        "team_founded": "Год основания: {year}",
        "team_upcoming": "📅 Ближайшие матчи",
        "team_recent": "🕘 Последние результаты",
        "no_upcoming": "Ближайших матчей не найдено.",
        "no_recent": "Последних результатов не найдено.",
        "fixtures_unavailable": "Сейчас не удалось загрузить список матчей.",
        "add_to_favorites": "⭐ Добавить в избранное",
        "remove_from_favorites": "🗑 Убрать из избранного",
        "team_page_unavailable": (
            "Сейчас не удалось загрузить данные команды."
        ),
        "news_unavailable": (
            "📰 <b>Новости</b>\n\n🚧 Этот раздел ещё не готов. "
            "Новости пока недоступны."
        ),
        "settings_title": "⚙️ <b>Настройки</b>\n\nВыберите язык:",
        "settings_timezone": "🕒 Часовой пояс: {tz}",
        "status_HT": "Перерыв",
        "status_FT": "Завершён",
        "status_AET": "Доп. время",
        "status_PEN": "Пенальти",
        "status_AWD": "Тех. результат",
        "status_WO": "Тех. результат",
        "status_PST": "Перенесён",
        "status_CANC": "Отменён",
        "status_ABD": "Прерван",
        "status_SUSP": "Приостановлен",
        "status_INT": "Перерыв",
        "status_TBD": "Время уточняется",
        "status_LIVE": "Live",
    },
    "en": {
        "live": "🔴 Live scores",
        "today": "📅 Today's matches",
        "find_team": "🔎 Find a team",
        "live_title": "🔴 <b>Live matches</b>",
        "today_title": "📅 <b>Today's matches</b> — {date}",
        "scope_top": "⭐ Top leagues",
        "scope_all": "🌍 All matches",
        "refresh": "🔄 Refresh",
        "no_live": "No live matches right now.",
        "no_today": "No matches found for today.",
        "no_top_matches": (
            "No matches in the selected major leagues and tournaments right now."
        ),
        "updated_at": "🕒 Updated: {time} ({tz})",
        "stale_notice": (
            "⚠️ Could not refresh the data. Last updated: {time}."
        ),
        "my_teams_section": "⭐ My teams",
        "standings_pick": "🏆 Choose a competition:",
        "country_leagues_title": "{flag} <b>{country}</b> competitions:",
        "no_country_leagues": "No competitions found for this country.",
        "standings_unavailable": (
            "No table is available for this competition right now."
        ),
        "standings_season": "Season {season}",
        "col_team": "Team",
        "col_played": "P",
        "col_gd": "GD",
        "col_points": "Pts",
        "team_country": "Country",
        "team_stadium": "Stadium",
        "team_founded": "Founded: {year}",
        "team_upcoming": "📅 Upcoming matches",
        "team_recent": "🕘 Recent results",
        "no_upcoming": "No upcoming matches found.",
        "no_recent": "No recent results found.",
        "fixtures_unavailable": "Could not load the match list right now.",
        "add_to_favorites": "⭐ Add to favorites",
        "remove_from_favorites": "🗑 Remove from favorites",
        "team_page_unavailable": "Could not load the team details right now.",
        "news_unavailable": (
            "📰 <b>News</b>\n\n🚧 This section is not ready yet. "
            "News is not available for now."
        ),
        "settings_title": "⚙️ <b>Settings</b>\n\nChoose your language:",
        "settings_timezone": "🕒 Time zone: {tz}",
        "status_HT": "HT",
        "status_FT": "FT",
        "status_AET": "AET",
        "status_PEN": "PEN",
        "status_AWD": "Awarded",
        "status_WO": "Walkover",
        "status_PST": "Postponed",
        "status_CANC": "Cancelled",
        "status_ABD": "Abandoned",
        "status_SUSP": "Suspended",
        "status_INT": "Interrupted",
        "status_TBD": "TBD",
        "status_LIVE": "LIVE",
    },
}
