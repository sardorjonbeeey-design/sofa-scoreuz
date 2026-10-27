# Flash Football

Telegram-first football assistant for Uzbekistan and Central Asia.

## What works today

| Menu button | Status | What it does |
|---|---|---|
| ⭐ My teams | **Working** | Saved favorites (PostgreSQL), open a team page, remove with ❌ |
| 🔴 Live scores | **Working** | Matches in play with minute and score; your teams first |
| 📅 Today's matches | **Working** | Today's fixtures with kickoff times in `DISPLAY_TIMEZONE` |
| 🏆 Standings | **Working** | Tables for 13 major competitions plus Uzbekistan's leagues |
| 🔎 Find a team | **Working** | Search → team page (stadium, next matches, last results) → add/remove favorite |
| ⚙️ Settings | **Working** | Language (Uzbek / Russian / English). Per-user time zone is not built |
| 📰 News 🚧 | **Not built** | There is no news data source. The button is marked 🚧 and says so |

Live and Today show "⭐ Top leagues" by default (featured competitions,
Uzbek leagues and your favorite teams) with one tap to "🌍 All matches".
Long lists are paginated.

Matches, standings and team data come from API-Football. League, team and
country names are shown exactly as the provider returns them (English);
the interface around them is translated.

News research/summarization and per-user time zone are not built yet. The archive stores structured fixtures, tournament tables, club profiles and current squads in PostgreSQL as the main bot refreshes those screens. Club profiles include official name, country/flag and stadium/capacity when available; market value is left unknown unless a reliable structured source provides it. TinyFish excerpts are internal research evidence only and are never posted as user-facing football knowledge.

### Verification status (read this before deploying)

The football screens are tested end to end against **mocked API-Football
responses** shaped like the provider's documented format. They have **not**
been run against the live API (no API key was available while building), so
check these on first deploy:

1. The league ids in `app/football/leagues.py` are well-known ids but are
   unverified. If an id returns a different competition than listed, the
   standings title still shows the provider's real name and the log says
   `League id N is listed as ... but the provider says ...`.
2. Error classification (quota / credentials / rate limit) follows the
   provider's documented `errors` shapes; unusual wording falls back to the
   generic "service unavailable" message and the details are logged.
3. Uzbek and Russian texts were written without a native-speaker review.
4. Quota header names (`x-ratelimit-requests-*`) are read when present and
   ignored when not.

## Architecture

    Telegram Bot (aiogram handlers)
        ↓
    PreferenceStore  ──→  PostgreSQL (users, favorite_teams)
        ↓
    FootballService ──(SnapshotCache: live, fixtures, standings)──┐
    TeamResolver ─────(MemoryCache: team search, details)────────┤
                                                                  ↓
                          CachingFootballProvider ──→ ApiFootballProvider
                                                      (one shared HTTP client)

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
| `DISPLAY_TIMEZONE` | no (default `Asia/Tashkent`) | IANA time zone that decides what "today" is and the kickoff times shown |
| `LIVE_CACHE_TTL_SECONDS` | no (default `60`) | Seconds live scores are shared between all users before API-Football is asked again |
| `FIXTURES_CACHE_TTL_SECONDS` | no (default `300`) | Same, for today's fixture list |
| `FREE_FAVORITE_SLOTS` | no (default `3`) | Favorite-team limit on the free plan |
| `DEFAULT_LANGUAGE` | no (default `uz`) | Language for users who have not chosen one (`uz`, `ru`, `en`) |
| `BOT_DISPLAY_NAME` | no | Display name |
| `LOG_LEVEL` | no (default `INFO`) | Python logging level |
| `PORT` | no (default `10000`) | Health-check server port; hosting platforms set this themselves |
| `SUPPORTER_BOT_TOKEN` | for archive automation | Token of the separate Supporter Bot; keep `BOT_TOKEN` for the main bot |
| `ARCHIVE_CHANNEL_ID` | for archive automation | Numeric Telegram channel ID where the Supporter Bot can post |
| `TINYFISH_API_KEY` | for archive automation | TinyFish Search API key; search is free within published limits |
| `ARCHIVE_FOUNDATION_INTERVAL_SECONDS` | no (default `86400`) | How often the Supporter Bot checks whether foundational profiles need refresh |
| `TEST_DATABASE_URL` | tests only | Optional empty PostgreSQL database for the PostgreSQL-specific tests (see Tests) |

## Archive collection

The main bot archives fixtures/results, tournament tables, and squads when users request those screens; writes happen on cache refresh, so archive collection does not add extra provider calls. Club metadata is stored by team ID with official/provider name, country/flag, stadium and capacity. Market value remains null unless sourced and verified. TinyFish search excerpts may be retained as internal research evidence, but are not published as club facts. Live scores are not archived on every refresh to avoid needless database churn.

## API usage and quota

Everything time-sensitive is cached once and shared by ALL users, so cost
depends on how long data may be reused, not on how many people use the bot.
Provider requests per kind of screen (cold cache):

| Screen | Requests | Reused for |
|---|---|---|
| Live scores | 1 | `LIVE_CACHE_TTL_SECONDS` (60 s) |
| Today's matches | 1 | `FIXTURES_CACHE_TTL_SECONDS` (5 min), new list at local midnight |
| A league's standings | 2 (season + table) | table 30 min, season 12 h |
| Uzbek leagues list | 1 | 12 h |
| Team page | 1 (+1 team details if not from a recent search) | fixtures 10 min, details 24 h |
| Team search | 1-3 | 6 h (10 min when nothing matched) |

Worst case with continuous use is about 1 440 live requests a day at the
default 60 s, which exceeds a 100-request free plan: raise
`LIVE_CACHE_TTL_SECONDS` / `FIXTURES_CACHE_TTL_SECONDS` to fit your plan.
The bot reads the daily quota the provider reports (and logs a warning when
fewer than 10 requests remain).

When the provider fails: quota and rate-limit errors back off for 60 s,
bad credentials for 5 min, outages for 5 s, so a failing provider is not
hammered. Today's fixtures, standings and team pages fall back to the last
good copy (clearly marked "could not refresh, last updated HH:MM") for up to
1 h / 24 h / 6 h. **Live scores are never shown stale.**

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
and need no credentials. Besides unit tests, the suite feeds real Telegram
`Update` objects through the real dispatcher and drives the real API client
over a mocked HTTP layer, and a "crawler" test presses every button reachable
from the main menu to make sure none is dead.

Two tests check PostgreSQL-only behavior (atomic rollback of a failed migration,
concurrent migration runs). They are skipped unless `TEST_DATABASE_URL` points to
an **empty, disposable** database whose name contains `test`; the tables
`users`, `favorite_teams` and `schema_migrations` in it are dropped.

## Provider

API-Football is used initially. Another provider can be added by implementing
`FootballProvider`.


### Supporter Bot archive setup

Set both `SUPPORTER_BOT_TOKEN` and `ARCHIVE_CHANNEL_ID` in the existing Render service. Add the bot to the channel as an administrator with posting permission. The supporter token is separate from `BOT_TOKEN`; do not overwrite the main bot token.

Archive automation requires `TINYFISH_API_KEY`, `SUPPORTER_BOT_TOKEN`, `ARCHIVE_CHANNEL_ID`, and a persistent `DATABASE_URL`. The archive keeps structured fixture, standings, squad and club-profile records in `archive_records`. TinyFish source snippets are not posted as public knowledge entries. `API_FOOTBALL_KEY` remains the structured football-data provider.
