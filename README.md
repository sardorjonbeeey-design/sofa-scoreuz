# Flash Football

Telegram-first football assistant for Uzbekistan and Central Asia.

## MVP

- Telegram bot
- Uzbek / Russian / English
- Favorite teams
- 3 free favorite-team slots
- Football API integration
- Team schedules
- Database layer
- Cache layer
- Notification foundation
- Archive foundation

## Architecture

Telegram Bot
    ↓
Application Services
    ↓
Football Provider Adapter
    ↓
Cache / Database
    ↓
Archive / Notifications

The football provider is isolated behind an adapter so the API can be
changed later without rewriting the rest of the application.

## Current Provider

API-Football is used initially.

A different provider can be added later through the same
`FootballProvider` interface.

## Running

Install dependencies:

```bash
pip install -r requirements.txt