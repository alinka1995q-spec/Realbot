from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Tariff, TariffPeriod


class TariffsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tariff_id: int) -> Optional[Tariff]:
        return await self.session.get(Tariff, tariff_id)

    async def list_active(self) -> list[Tariff]:
        res = await self.session.execute(
            select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.sort_order, Tariff.id)
        )
        return list(res.scalars())

    async def list_all(self) -> list[Tariff]:
        res = await self.session.execute(select(Tariff).order_by(Tariff.sort_order, Tariff.id))
        return list(res.scalars())

    async def create(
        self,
        *,
        name: str,
        description: Optional[str],
        min_amount: Decimal,
        max_amount: Decimal,
        duration_days: int,
        period: TariffPeriod,
        period_n_days: int,
        payout_percent: Optional[Decimal] = None,
        payout_fixed: Optional[Decimal] = None,
        body_included: bool = True,
        sort_order: int = 0,
        max_purchases: int = 0,
    ) -> Tariff:
        tariff = Tariff(
            name=name,
            description=description,
            min_amount=min_amount,
            max_amount=max_amount,
            duration_days=duration_days,
            period=period.value,
            period_n_days=period_n_days,
            payout_percent=payout_percent,
            payout_fixed=payout_fixed,
            body_included=body_included,
            sort_order=sort_order,
            max_purchases=max_purchases,
        )
        self.session.add(tariff)
        await self.session.flush()
        return tariff

    async def update(self, tariff_id: int, **fields) -> None:
        if not fields:
            return
        await self.session.execute(
            update(Tariff).where(Tariff.id == tariff_id).values(**fields)
        )

    async def set_active(self, tariff_id: int, is_active: bool) -> None:
        await self.update(tariff_id, is_active=is_active)
