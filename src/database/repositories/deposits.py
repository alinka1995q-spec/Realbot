from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models import Deposit, DepositStatus, Tariff


class DepositsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, deposit_id: int) -> Optional[Deposit]:
        res = await self.session.execute(
            select(Deposit).options(joinedload(Deposit.tariff)).where(Deposit.id == deposit_id)
        )
        return res.scalar_one_or_none()

    async def get_by_hash(self, receipt_hash: str) -> Optional[Deposit]:
        res = await self.session.execute(
            select(Deposit).where(Deposit.receipt_hash == receipt_hash)
        )
        return res.scalar_one_or_none()

    async def create_pending(
        self,
        *,
        user_id: int,
        tariff_id: int,
        amount: Decimal,
        receipt_file_id: Optional[str],
        receipt_hash: Optional[str],
        payout_full_name: Optional[str],
        payout_bank: Optional[str],
        payout_number: Optional[str],
        requisite_id: Optional[int],
    ) -> Deposit:
        d = Deposit(
            user_id=user_id,
            tariff_id=tariff_id,
            amount=amount,
            status=DepositStatus.PENDING.value,
            receipt_file_id=receipt_file_id,
            receipt_hash=receipt_hash,
            payout_full_name=payout_full_name,
            payout_bank=payout_bank,
            payout_number=payout_number,
            requisite_id=requisite_id,
        )
        self.session.add(d)
        await self.session.flush()
        return d

    async def set_status(self, deposit_id: int, status: DepositStatus, **extra) -> None:
        await self.session.execute(
            update(Deposit).where(Deposit.id == deposit_id).values(status=status.value, **extra)
        )

    async def update_fields(self, deposit_id: int, **fields) -> None:
        if not fields:
            return
        await self.session.execute(update(Deposit).where(Deposit.id == deposit_id).values(**fields))

    async def list_user(self, user_id: int, limit: int = 50) -> list[Deposit]:
        res = await self.session.execute(
            select(Deposit)
            .options(joinedload(Deposit.tariff))
            .where(Deposit.user_id == user_id)
            .order_by(Deposit.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())

    async def list_by_status(self, status: DepositStatus, limit: int = 100, offset: int = 0) -> list[Deposit]:
        res = await self.session.execute(
            select(Deposit)
            .options(joinedload(Deposit.tariff))
            .where(Deposit.status == status.value)
            .order_by(Deposit.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(res.scalars())

    async def count_by_status(self, status: DepositStatus) -> int:
        res = await self.session.execute(
            select(func.count(Deposit.id)).where(Deposit.status == status.value)
        )
        return int(res.scalar_one())

    async def count_user_tariff(self, user_id: int, tariff_id: int) -> int:
        """Сколько уже куплено (pending/active/completed) этого тарифа этим пользователем."""
        res = await self.session.execute(
            select(func.count(Deposit.id)).where(
                Deposit.user_id == user_id,
                Deposit.tariff_id == tariff_id,
                Deposit.status.in_([
                    DepositStatus.PENDING.value,
                    DepositStatus.ACTIVE.value,
                    DepositStatus.COMPLETED.value,
                ]),
            )
        )
        return int(res.scalar_one())

    async def sum_active(self) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0)).where(Deposit.status == DepositStatus.ACTIVE.value)
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_confirmed_total(self) -> Decimal:
        """Сумма всех подтверждённых депозитов (active + completed)."""
        res = await self.session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0)).where(
                Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value])
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_confirmed_since(self, since: datetime) -> Decimal:
        """Сумма подтверждённых депозитов, созданных после указанного времени."""
        res = await self.session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0)).where(
                Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value]),
                Deposit.created_at >= since,
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def has_active(self, user_id: int) -> bool:
        res = await self.session.execute(
            select(func.count(Deposit.id)).where(
                and_(Deposit.user_id == user_id, Deposit.status == DepositStatus.ACTIVE.value)
            )
        )
        return int(res.scalar_one()) > 0

    async def has_any_confirmed(self, user_id: int) -> bool:
        res = await self.session.execute(
            select(func.count(Deposit.id)).where(
                and_(
                    Deposit.user_id == user_id,
                    Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value]),
                )
            )
        )
        return int(res.scalar_one()) > 0

    async def deposits_by_day(self, days: int) -> list[tuple[str, int, Decimal]]:
        """Возвращает [(YYYY-MM-DD, count, sum)] за последние N дней (только confirmed).
        Работает кросс-БД (SQLite/Postgres) - агрегация на стороне Python.
        """
        from collections import defaultdict
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        res = await self.session.execute(
            select(Deposit.created_at, Deposit.amount).where(
                Deposit.status.in_(
                    [DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value]
                ),
                Deposit.created_at >= cutoff,
            )
        )
        counts: dict[str, int] = defaultdict(int)
        sums: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for created_at, amount in res:
            if created_at is None:
                continue
            key = created_at.strftime("%Y-%m-%d")
            counts[key] += 1
            sums[key] += Decimal(amount or 0)
        return [(d, counts[d], sums[d]) for d in sorted(counts.keys())]

    async def find_active_for_completion(self, now: datetime) -> list[int]:
        """Возвращает id депозитов, у которых пора менять статус на completed."""
        res = await self.session.execute(
            select(Deposit.id).where(
                Deposit.status == DepositStatus.ACTIVE.value,
                Deposit.ends_at <= now,
            )
        )
        return [row[0] for row in res]
