from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import FavoriteTeam, User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(
        self,
        telegram_id: int,
    ) -> User | None:

        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id
            )
        )

        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        language: str = "uz",
    ) -> User:

        user = await self.get_by_telegram_id(telegram_id)

        if user:
            return user

        user = User(
            telegram_id=telegram_id,
            language=language,
        )

        self.session.add(user)

        try:
            await self.session.commit()
        except IntegrityError:
            # Another request created the same user first.
            await self.session.rollback()

            existing = await self.get_by_telegram_id(telegram_id)

            if existing is None:
                raise

            return existing

        await self.session.refresh(user)

        return user

    async def set_language(
        self,
        telegram_id: int,
        language: str,
    ) -> User:

        user = await self.get_or_create(telegram_id, language)

        if user.language != language:
            user.language = language
            await self.session.commit()
            await self.session.refresh(user)

        return user


class FavoriteTeamRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def count_for_user(
        self,
        user_id: int,
    ) -> int:

        result = await self.session.execute(
            select(
                func.count(FavoriteTeam.id)
            ).where(
                FavoriteTeam.user_id == user_id
            )
        )

        return int(result.scalar_one())

    async def exists(
        self,
        user_id: int,
        team_id: int,
    ) -> bool:

        result = await self.session.execute(
            select(FavoriteTeam.id).where(
                FavoriteTeam.user_id == user_id,
                FavoriteTeam.team_id == team_id,
            )
        )

        return result.first() is not None

    async def add(
        self,
        user_id: int,
        team_id: int,
        team_name: str,
        team_type: str = "club",
    ) -> FavoriteTeam:

        favorite = FavoriteTeam(
            user_id=user_id,
            team_id=team_id,
            team_name=team_name,
            team_type=team_type,
        )

        self.session.add(favorite)

        await self.session.commit()
        await self.session.refresh(favorite)

        return favorite

    async def remove(
        self,
        user_id: int,
        team_id: int,
    ) -> bool:
        """Delete a favorite. Returns True if a row was removed."""

        result = await self.session.execute(
            delete(FavoriteTeam).where(
                FavoriteTeam.user_id == user_id,
                FavoriteTeam.team_id == team_id,
            )
        )

        await self.session.commit()

        return (result.rowcount or 0) > 0

    async def list_for_user(
        self,
        user_id: int,
    ) -> list[FavoriteTeam]:

        result = await self.session.execute(
            select(FavoriteTeam)
            .where(
                FavoriteTeam.user_id == user_id
            )
            .order_by(FavoriteTeam.id)
        )

        return list(result.scalars().all())
