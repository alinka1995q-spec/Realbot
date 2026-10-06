from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Withdrawal, WithdrawalStatus
from src.database.repositories.admins import valid_admin_id


class WithdrawalsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        amount: Decimal,
        bank: str,
        number: str,
        holder_name: Optional[str],
    ) -> Withdrawal:
        w = Withdrawal(
            user_id=user_id,
            amount=amount,
            bank=bank,
            number=number,
            holder_name=holder_name,
        )
        self.session.add(w)
        await self.session.flush()
        return w

    async def get(self, withdrawal_id: int) -> Optional[Withdrawal]:
        return await self.session.get(Withdrawal, withdrawal_id)

    async def list_by_status(self, status: WithdrawalStatus, limit: int = 50) -> list[Withdrawal]:
        res = await self.session.execute(
            select(Withdrawal)
            .where(Withdrawal.status == status.value)
            .order_by(Withdrawal.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())

    async def list_user(self, user_id: int, limit: int = 50) -> list[Withdrawal]:
        res = await self.session.execute(
            select(Withdrawal)
            .where(Withdrawal.user_id == user_id)
            .order_by(Withdrawal.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())

    async def set_status(
        self,
        withdrawal_id: int,
        status: WithdrawalStatus,
        admin_id: Optional[int] = None,
        rejected_reason: Optional[str] = None,
    ) -> None:
        admin_id = await valid_admin_id(self.session, admin_id)
        await self.session.execute(
            update(Withdrawal)
            .where(Withdrawal.id == withdrawal_id)
            .values(
                status=status.value,
                processed_by_admin_id=admin_id,
                rejected_reason=rejected_reason,
                processed_at=datetime.now(timezone.utc),
            )
        )

    async def sum_paid(self) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
                Withdrawal.status == WithdrawalStatus.APPROVED.value
            )
        )
        return Decimal(res.scalar_one() or 0)

    async def sum_paid_since(self, since: datetime) -> Decimal:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
                Withdrawal.status == WithdrawalStatus.APPROVED.value,
                Withdrawal.processed_at >= since,
            )
        )
        return Decimal(res.scalar_one() or 0)
