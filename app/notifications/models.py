from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationPreference:
    goals: bool = True
    cards: bool = False
    substitutions: bool = False
    lineups: bool = False
    full_time: bool = True
    important_news: bool = False