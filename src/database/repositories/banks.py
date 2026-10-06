from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Bank


class BanksRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Bank]:
        res = await self.session.execute(
            select(Bank).where(Bank.is_active.is_(True)).order_by(Bank.category, Bank.sort_order, Bank.id)
        )
        return list(res.scalars())

    async def list_all(self) -> list[Bank]:
        res = await self.session.execute(
            select(Bank).order_by(Bank.category, Bank.sort_order, Bank.id)
        )
        return list(res.scalars())

    async def list_active_categories(self) -> list[str]:
        """Уникальные категории среди активных банков, в порядке появления."""
        res = await self.session.execute(
            select(Bank.category).where(Bank.is_active.is_(True))
            .order_by(Bank.category)
        )
        seen: list[str] = []
        for (cat,) in res:
            if cat not in seen:
                seen.append(cat)
        return seen

    async def list_active_in_category(self, category: str) -> list[Bank]:
        res = await self.session.execute(
            select(Bank)
            .where(Bank.is_active.is_(True), Bank.category == category)
            .order_by(Bank.sort_order, Bank.id)
        )
        return list(res.scalars())

    async def get(self, bank_id: int) -> Optional[Bank]:
        return await self.session.get(Bank, bank_id)

    async def get_by_name(self, name: str) -> Optional[Bank]:
        res = await self.session.execute(select(Bank).where(Bank.name == name))
        return res.scalar_one_or_none()

    async def create(self, *, name: str, category: str = "Банки", sort_order: int = 0) -> Bank:
        existing = await self.get_by_name(name)
        if existing:
            return existing
        b = Bank(name=name, category=category, sort_order=sort_order)
        self.session.add(b)
        await self.session.flush()
        return b

    async def update(self, bank_id: int, **fields) -> None:
        if not fields:
            return
        await self.session.execute(update(Bank).where(Bank.id == bank_id).values(**fields))

    async def set_active(self, bank_id: int, is_active: bool) -> None:
        await self.update(bank_id, is_active=is_active)

    async def delete(self, bank_id: int) -> None:
        b = await self.get(bank_id)
        if b is not None:
            await self.session.delete(b)
