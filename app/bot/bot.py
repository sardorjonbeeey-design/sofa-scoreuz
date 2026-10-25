from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Settings
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.teams import router as teams_router
from app.football.team_directory import TeamDirectory
from app.football.team_resolver import TeamResolver
from app.storage.store import MemoryPreferenceStore, PreferenceStore


def create_bot(token: str) -> Bot:
    if not token:
        raise ValueError("BOT_TOKEN is not configured.")

    return Bot(
        token=token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )


def create_dispatcher(
    settings: Settings,
    store: PreferenceStore | None = None,
    resolver: TeamResolver | None = None,
    directory: TeamDirectory | None = None,
) -> Dispatcher:
    # FSM storage only holds the short-lived "waiting for a team
    # name" state. Language and favorites are NOT kept here: they
    # live in ``store`` (PostgreSQL when DATABASE_URL is configured).
    #
    # Everything passed as a keyword argument below is injected into
    # handlers by parameter name.
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        store=store or MemoryPreferenceStore(settings.default_language),
        resolver=resolver,
        directory=directory or TeamDirectory(),
    )

    dispatcher.include_router(start_router)
    dispatcher.include_router(menu_router)
    dispatcher.include_router(teams_router)

    return dispatcher
