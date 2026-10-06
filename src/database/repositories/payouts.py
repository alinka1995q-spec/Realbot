from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models import Deposit, Payout, PayoutStatus
from src.database.repositories.admins import valid_admin_id


class PayoutsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payout_id: int) -> Optional[Payout]:
        return await self.session.get(Payout, payout_id)

    async def get_with_deposit(self, payout_id: int) -> Optional[Payout]:
        res = await self.session.execute(
            select(Payout).options(joinedload(Payout.deposit).joinedload(Deposit.tariff)).where(Payout.id == payout_id)
        )
        return res.scalar_one_or_none()

    async def bulk_create(self, items: list[dict]) -> None:
        self.session.add_all([Payout(**i) for i in items])
        await self.session.flush()

    async def list_for_deposit(self, deposit_id: int) -> list[Payout]:
        res = await self.session.execute(
            select(Payout).where(Payout.deposit_id == deposit_id).order_by(Payout.seq)
        )
        return list(res.scalars())

    async def due_pending(self, now: datetime, limit: int = 100) -> list[Payout]:
        res = await self.session.execute(
            select(Payout)
            .options(joinedload(Payout.deposit))
            .where(Payout.status == PayoutStatus.PENDING.value, Payout.due_at <= now)
            .order_by(Payout.due_at)
            .limit(limit)
        )
        return list(res.scalars())

    async def list_by_status(self, status: PayoutStatus, limit: int = 100, offset: int = 0) -> list[Payout]:
        res = await self.session.execute(
            select(Payout)
            .options(joinedload(Payout.deposit))
            .where(Payout.status == status.value)
            .order_by(Payout.due_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(res.scalars())

    async def list_pending_in_range(
        self, since: datetime, until: datetime, limit: int = 500
    ) -> list[Payout]:
        from src.database.models import Deposit

        res = await self.session.execute(
            select(Payout)
            .options(joinedload(Payout.deposit).joinedload(Deposit.tariff))
            .where(
                Payout.status == PayoutStatus.PENDING.value,
                Payout.due_at >= since,
                Payout.due_at < until,
            )
            .order_by(Payout.due_at.asc())
            .limit(limit)
        )
        return list(res.scalars())

    async def list_pending_overdue(self, now: datetime, limit: int = 500) -> list[Payout]:
        from src.database.models import Deposit

        res = await self.session.execute(
            select(Payout)
            .options(joinedload(Payout.deposit).joinedload(Deposit.tariff))
            .where(
                Payout.status == PayoutStatus.PENDING.value,
                Payout.due_at < now,
            )
            .order_by(Payout.due_at.asc())
            .limit(limit)
        )
        return list(res.scalars())

    async def mark_paid(self, payout_id: int, admin_id: Optional[int]) -> None:
        admin_id = await valid_admin_id(self.session, admin_id)
        await self.session.execute(
            update(Payout)
            .where(Payout.id == payout_id)
            .values(status=PayoutStatus.PAID.value, paid_at=datetime.now(timezone.utc), paid_by_admin_id=admin_id)
        )

    async def mark_cancelled(self, payout_id: int) -> None:
        await self.session.execute(
            update(Payout).where(Payout.id == payout_id).values(status=PayoutStatus.CANCELLED.value)
        )

    async def sum_paid(self) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Payout.amount), 0)).where(
                Payout.status == PayoutStatus.PAID.value
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_paid_since(self, since: datetime) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Payout.amount), 0)).where(
                Payout.status == PayoutStatus.PAID.value,
                Payout.paid_at >= since,
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def count_by_status(self, status: PayoutStatus) -> int:
        res = await self.session.execute(
            select(func.count(Payout.id)).where(Payout.status == status.value)
        )
        return int(res.scalar_one())

    async def payouts_by_day(self, days: int) -> list[tuple[str, int, Decimal]]:
        """Кросс-БД агрегация на стороне Python."""
        from collections import defaultdict
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        res = await self.session.execute(
            select(Payout.paid_at, Payout.amount).where(
                Payout.status == PayoutStatus.PAID.value,
                Payout.paid_at >= cutoff,
            )
        )
        counts: dict[str, int] = defaultdict(int)
        sums: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for paid_at, amount in res:
            if paid_at is None:
                continue
            key = paid_at.strftime("%Y-%m-%d")
            counts[key] += 1
            sums[key] += Decimal(amount or 0)
        return [(d, counts[d], sums[d]) for d in sorted(counts.keys())]
