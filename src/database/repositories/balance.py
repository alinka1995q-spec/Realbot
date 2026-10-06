from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import BalanceChange, BalanceChangeReason
from src.database.repositories.admins import valid_admin_id


class BalanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reason: BalanceChangeReason,
        ref_id: Optional[int] = None,
        comment: Optional[str] = None,
        admin_id: Optional[int] = None,
    ) -> BalanceChange:
        admin_id = await valid_admin_id(self.session, admin_id)
        bc = BalanceChange(
            user_id=user_id,
            amount=amount,
            reason=reason.value,
            ref_id=ref_id,
            comment=comment,
            admin_id=admin_id,
        )
        self.session.add(bc)
        await self.session.flush()
        return bc

    async def list_user(self, user_id: int, limit: int = 50) -> list[BalanceChange]:
        res = await self.session.execute(
            select(BalanceChange)
            .where(BalanceChange.user_id == user_id)
            .order_by(BalanceChange.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())
