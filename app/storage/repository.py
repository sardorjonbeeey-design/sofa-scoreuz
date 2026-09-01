from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import FavoriteTeam, User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self,
        telegram_id: int,
        language: str = "uz",
    ) -> User:

        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id
            )
        )

        user = result.scalar_one_or_none()

        if user:
            return user

        user = User(
            telegram_id=telegram_id,
            language=language,
        )

        self.session.add(user)

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

    async def add(
        self,
        user_id: int,
        team_id: int,
        team_name: str,
    ) -> FavoriteTeam:

        favorite = FavoriteTeam(
            user_id=user_id,
            team_id=team_id,
            team_name=team_name,
        )

        self.session.add(favorite)

        await self.session.commit()
        await self.session.refresh(favorite)

        return favorite

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