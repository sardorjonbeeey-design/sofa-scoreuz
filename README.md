# Flash Football

Telegram-first football assistant for Uzbekistan and Central Asia.

## Current features

- Telegram bot in Uzbek / Russian / English
- Language and favorite teams **saved in PostgreSQL** (survive restarts and redeploys)
- Team search through API-Football, add and remove favorites
- 3 free favorite-team slots (configurable, see `FREE_FAVORITE_SLOTS`)
- Provider failures (quota, credentials, outages) are reported honestly instead of as "team not found"
- Health-check HTTP server for the hosting platform

Matches, News, Standings, Notifications and the Archive are still placeholders.

## Architecture

    Telegram Bot (aiogram handlers)
        ↓
    PreferenceStore  ──→  PostgreSQL (users, favorite_teams)
        ↓
    TeamResolver ──→ CachingFootballProvider ──→ ApiFootballProvider
                         (MemoryCache)             (one shared HTTP client)

The football provider sits behind the `FootballProvider` interface, so
API-Football can be replaced without touching the rest of the app.

## Environment variables

Names only. Never commit real values; `.env` is git-ignored.

| Variable | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | yes | Telegram bot token from @BotFather |
| `API_FOOTBALL_KEY` | for team search | API-Football credential. Without it the bot runs but search is disabled |
| `DATABASE_URL` | for persistence | PostgreSQL URL. `postgres://`, `postgresql://` and a trailing `?sslmode=...` are accepted. Empty = data kept in memory only |
| `REQUIRE_DATABASE` | recommended in production | `true` makes the bot refuse to start without `DATABASE_URL`, so a missing variable can never silently turn persistence off |
| `FREE_FAVORITE_SLOTS` | no (default `3`) | Favorite-team limit on the free plan |
| `DEFAULT_LANGUAGE` | no (default `uz`) | Language for users who have not chosen one (`uz`, `ru`, `en`) |
| `BOT_DISPLAY_NAME` | no | Display name |
| `LOG_LEVEL` | no (default `INFO`) | Python logging level |
| `PORT` | no (default `10000`) | Health-check server port; hosting platforms set this themselves |
| `TEST_DATABASE_URL` | tests only | Optional empty PostgreSQL database for the PostgreSQL-specific tests (see Tests) |

## Run locally

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # then fill in BOT_TOKEN (and API_FOOTBALL_KEY)
    python -m app.main

These three commands start the same application:

    python -m app.main
    python main.py
    python -m app

With no `DATABASE_URL` the bot logs a warning and keeps favorites in memory
(lost on restart). For a local database use a PostgreSQL URL.

## Database and migrations

Tables are managed by a small versioned migration runner
(`app/storage/migrations.py`). It runs automatically at startup, only ever
creates or alters (never drops), records what it applied in `schema_migrations`,
and on PostgreSQL uses an advisory lock so two overlapping instances cannot
race. Nothing to run by hand.

To change the schema later: edit `app/storage/models.py`, then **append** a new
`Migration` with the next version number. Never edit a released migration.

If the database is unreachable at startup the bot keeps running; any action
that needs to save data tells the user it could not be saved and retries the
connection on the next request. Nothing is ever reported as saved when it was not.

### Supabase / PgBouncer

Connection-pooler URLs (transaction mode, port 6543) work: prepared-statement
caching is disabled for asyncpg. This was tested against PgBouncer in
transaction mode.

## Deploy on Render

- Build command: `pip install -r requirements.txt`
- Start command: `python -m app.main` (`python main.py` is equivalent)
- Environment variables: `BOT_TOKEN`, `API_FOOTBALL_KEY`, `DATABASE_URL`,
  `REQUIRE_DATABASE=true`, optionally the others in the table above
- The health server binds `PORT` before anything else starts, and
  `/` and `/health` return a plain-text OK.

During a deploy Render can briefly run the old and new instance together.
Telegram allows one polling client per bot, so you may see short-lived
"Conflict" warnings in the logs until the old instance stops.

## Tests

    pip install -r requirements-dev.txt
    pytest

Tests use mocks and in-memory SQLite. They never call API-Football or Telegram
and need no credentials.

Two tests check PostgreSQL-only behavior (atomic rollback of a failed migration,
concurrent migration runs). They are skipped unless `TEST_DATABASE_URL` points to
an **empty, disposable** database whose name contains `test`; the tables
`users`, `favorite_teams` and `schema_migrations` in it are dropped.

## Provider

API-Football is used initially. Another provider can be added by implementing
`FootballProvider`.
