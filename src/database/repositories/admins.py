from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Admin, AdminLog, AdminRole


async def valid_admin_id(session: AsyncSession, admin_id: Optional[int]) -> Optional[int]:
    """Возвращает admin_id если такая запись существует, иначе None.
    Защищает от FK-ошибок когда в сессии остался id уже удалённого админа."""
    if admin_id is None:
        return None
    res = await session.execute(select(Admin.id).where(Admin.id == admin_id))
    return res.scalar_one_or_none()


class AdminsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tg(self, tg_id: int) -> Optional[Admin]:
        res = await self.session.execute(select(Admin).where(Admin.telegram_id == tg_id))
        return res.scalar_one_or_none()

    async def is_admin(self, tg_id: int) -> bool:
        return (await self.get_by_tg(tg_id)) is not None

    async def list_all(self) -> list[Admin]:
        res = await self.session.execute(select(Admin).order_by(Admin.is_root.desc(), Admin.created_at))
        return list(res.scalars())

    async def add(
        self,
        tg_id: int,
        *,
        name: Optional[str] = None,
        username: Optional[str] = None,
        role: AdminRole = AdminRole.ADMIN,
        is_root: bool = False,
    ) -> Admin:
        existing = await self.get_by_tg(tg_id)
        if existing:
            return existing
        admin = Admin(
            telegram_id=tg_id,
            name=name,
            username=username,
            role=role.value,
            is_root=is_root,
        )
        self.session.add(admin)
        await self.session.flush()
        return admin

    async def remove(self, admin_id: int) -> bool:
        admin = await self.session.get(Admin, admin_id)
        if not admin or admin.is_root:
            return False
        await self.session.delete(admin)
        return True

    async def log(
        self,
        admin_id: Optional[int],
        action: str,
        *,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        payload: Optional[dict] = None,
        ip: Optional[str] = None,
    ) -> None:
        admin_id = await valid_admin_id(self.session, admin_id)
        self.session.add(
            AdminLog(
                admin_id=admin_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                payload=payload,
                ip=ip,
                created_at=datetime.now(timezone.utc),
            )
        )
