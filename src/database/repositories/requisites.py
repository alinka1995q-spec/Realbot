from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Requisite


class RequisitesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Requisite]:
        res = await self.session.execute(
            select(Requisite).where(Requisite.is_active.is_(True)).order_by(Requisite.sort_order, Requisite.id)
        )
        return list(res.scalars())

    async def list_all(self) -> list[Requisite]:
        res = await self.session.execute(select(Requisite).order_by(Requisite.sort_order, Requisite.id))
        return list(res.scalars())

    async def get(self, req_id: int) -> Optional[Requisite]:
        return await self.session.get(Requisite, req_id)

    async def create(self, *, bank: str, number: str, holder_name: Optional[str] = None, comment: Optional[str] = None) -> Requisite:
        r = Requisite(bank=bank, number=number, holder_name=holder_name, comment=comment)
        self.session.add(r)
        await self.session.flush()
        return r

    async def set_active(self, req_id: int, is_active: bool) -> None:
        await self.session.execute(
            update(Requisite).where(Requisite.id == req_id).values(is_active=is_active)
        )

    async def update(self, req_id: int, **fields) -> None:
        if not fields:
            return
        await self.session.execute(update(Requisite).where(Requisite.id == req_id).values(**fields))

    async def pick_one_active(self) -> Optional[Requisite]:
        """Возвращает любой активный реквизит (для авто-распределения)."""
        items = await self.list_active()
        return items[0] if items else None
