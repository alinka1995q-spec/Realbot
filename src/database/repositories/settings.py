from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import SettingsKV


class SettingsRepo:
    """Хранилище глобальных настроек (ключ-значение)."""

    DEFAULTS: dict[str, str] = {
        "ref_percent_l1": "10",
        "ref_percent_l2": "5",
        "ref_percent_l3": "1",
        "min_withdrawal": "100",
        "support_username": "",
        "require_active_deposit_for_withdraw_ref": "true",
        "required_channel": "",
        "required_group": "",
        "investors_group_invite": "",
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        res = await self.session.execute(select(SettingsKV.value).where(SettingsKV.key == key))
        v = res.scalar_one_or_none()
        if v is None:
            return default if default is not None else self.DEFAULTS.get(key)
        return v

    async def set(self, key: str, value: str) -> None:
        existing = await self.session.execute(
            select(SettingsKV.key).where(SettingsKV.key == key)
        )
        if existing.scalar_one_or_none() is None:
            self.session.add(SettingsKV(key=key, value=value))
        else:
            await self.session.execute(
                update(SettingsKV).where(SettingsKV.key == key).values(value=value)
            )

    async def get_decimal(self, key: str, default: Decimal = Decimal(0)) -> Decimal:
        v = await self.get(key)
        if v is None:
            return default
        try:
            return Decimal(v)
        except Exception:
            return default

    async def get_bool(self, key: str, default: bool = False) -> bool:
        v = await self.get(key)
        if v is None:
            return default
        return v.lower() in {"1", "true", "yes", "on"}

    async def get_ref_percents(self) -> tuple[Decimal, Decimal, Decimal]:
        return (
            await self.get_decimal("ref_percent_l1", Decimal("10")),
            await self.get_decimal("ref_percent_l2", Decimal("5")),
            await self.get_decimal("ref_percent_l3", Decimal("1")),
        )
