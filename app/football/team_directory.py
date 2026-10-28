from app.cache.cache import MemoryCache
from app.football.models import Team

# How long a search result stays selectable from its inline button.
DIRECTORY_TTL_SECONDS = 6 * 60 * 60


class TeamDirectory:
    """Short-lived lookup of teams that were just shown to users.

    Inline buttons only carry a compact team id. This directory maps
    that id back to the team returned by the provider, so team names
    never travel inside callback data and can never be spoofed by a
    forged callback.

    Entries expire (and are lost on restart). Callers must treat a
    miss as "search expired" and ask the user to search again.
    """

    def __init__(
        self,
        cache: MemoryCache | None = None,
        ttl_seconds: int = DIRECTORY_TTL_SECONDS,
    ):
        self.cache = (
            cache if cache is not None else MemoryCache(max_items=5000)
        )
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(team_id: int) -> str:
        return f"team:{team_id}"

    async def remember(self, teams: list[Team]) -> None:
        for team in teams:
            await self.cache.set(
                self._key(team.id),
                team,
                self.ttl_seconds,
            )

    async def get(self, team_id: int) -> Team | None:
        return await self.cache.get(self._key(team_id))
