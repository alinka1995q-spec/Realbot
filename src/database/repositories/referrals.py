from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ReferralEarning, User


class ReferralsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_earning(
        self,
        *,
        to_user_id: int,
        from_user_id: int,
        deposit_id: int,
        level: int,
        percent: Decimal,
        amount: Decimal,
    ) -> ReferralEarning:
        e = ReferralEarning(
            to_user_id=to_user_id,
            from_user_id=from_user_id,
            deposit_id=deposit_id,
            level=level,
            percent=percent,
            amount=amount,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(e)
        await self.session.flush()
        return e

    async def list_for_user(self, user_id: int, limit: int = 50) -> list[ReferralEarning]:
        res = await self.session.execute(
            select(ReferralEarning)
            .where(ReferralEarning.to_user_id == user_id)
            .order_by(ReferralEarning.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())

    async def sum_for_user(self, user_id: int) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount), 0)).where(
                ReferralEarning.to_user_id == user_id
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_total(self) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount), 0))
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_since(self, since: datetime) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount), 0)).where(
                ReferralEarning.created_at >= since
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def top_referrers(self, limit: int = 10) -> list[tuple[int, str, int, Decimal]]:
        """Возвращает топ по количеству приглашённых рефералов 1 уровня."""
        stmt = (
            select(
                User.id,
                User.username,
                func.count(ReferralEarning.id).label("earnings_count"),
                func.coalesce(func.sum(ReferralEarning.amount), 0).label("earnings_sum"),
            )
            .join(ReferralEarning, ReferralEarning.to_user_id == User.id, isouter=True)
            .group_by(User.id, User.username)
            .order_by(func.coalesce(func.sum(ReferralEarning.amount), 0).desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [(int(r[0]), r[1], int(r[2]), Decimal(r[3])) for r in res]
