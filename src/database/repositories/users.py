from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User


class UsersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, tg_id: int) -> Optional[User]:
        res = await self.session.execute(select(User).where(User.telegram_id == tg_id))
        return res.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        return await self.session.get(User, user_id)

    async def get_or_create(
        self,
        telegram_id: int,
        *,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        lang: str = "ru",
        referrer_id: Optional[int] = None,
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            changed = False
            if username and user.username != username:
                user.username = username
                changed = True
            if full_name and user.full_name != full_name:
                user.full_name = full_name
                changed = True
            user.last_active_at = datetime.now(timezone.utc)
            if changed:
                await self.session.flush()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            lang=lang,
            referrer_id=referrer_id,
            last_active_at=datetime.now(timezone.utc),
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def update_phone(self, user_id: int, phone: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(phone=phone)
        )

    async def update_lang(self, user_id: int, lang: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(lang=lang)
        )

    async def set_blocked(self, user_id: int, is_blocked: bool, reason: Optional[str] = None) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_blocked=is_blocked, blocked_reason=reason)
        )

    async def count_total(self) -> int:
        res = await self.session.execute(select(func.count(User.id)))
        return int(res.scalar_one())

    async def count_since(self, since: datetime) -> int:
        res = await self.session.execute(
            select(func.count(User.id)).where(User.created_at >= since)
        )
        return int(res.scalar_one())

    async def count_active_since(self, since: datetime) -> int:
        res = await self.session.execute(
            select(func.count(User.id)).where(User.last_active_at >= since)
        )
        return int(res.scalar_one())

    async def search(self, q: str, limit: int = 50) -> list[User]:
        from sqlalchemy import or_

        from src.database.models import Deposit, Withdrawal

        like = f"%{q}%"
        try:
            tg_id = int(q)
        except ValueError:
            tg_id = None
        conditions = [
            User.username.ilike(like),
            User.full_name.ilike(like),
            User.phone.ilike(like),
        ]
        if tg_id is not None:
            conditions.append(User.telegram_id == tg_id)
            conditions.append(User.id == tg_id)

        # Подзапросы: user_ids у которых есть депозиты/выводы с подходящими реквизитами
        dep_user_ids = (
            select(Deposit.user_id)
            .where(
                or_(
                    Deposit.payout_number.ilike(like),
                    Deposit.payout_full_name.ilike(like),
                    Deposit.payout_bank.ilike(like),
                )
            )
            .distinct()
        )
        wd_user_ids = (
            select(Withdrawal.user_id)
            .where(
                or_(
                    Withdrawal.number.ilike(like),
                    Withdrawal.holder_name.ilike(like),
                    Withdrawal.bank.ilike(like),
                )
            )
            .distinct()
        )
        conditions.append(User.id.in_(dep_user_ids))
        conditions.append(User.id.in_(wd_user_ids))

        stmt = select(User).where(or_(*conditions)).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars())

    async def add_to_balance(self, user_id: int, delta: Decimal) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(balance=User.balance + delta)
        )

    async def list_active_telegram_ids(self, days: int = 30) -> list[int]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        res = await self.session.execute(
            select(User.telegram_id).where(User.last_active_at >= since, User.is_blocked.is_(False))
        )
        return [row[0] for row in res]

    async def list_all_telegram_ids(self) -> list[int]:
        res = await self.session.execute(
            select(User.telegram_id).where(User.is_blocked.is_(False))
        )
        return [row[0] for row in res]

    async def referrer_chain(self, user_id: int, depth: int = 3) -> list[int]:
        """Возвращает список user_id рефереров, начиная с 1 уровня."""
        chain: list[int] = []
        current_id: Optional[int] = user_id
        for _ in range(depth):
            if current_id is None:
                break
            res = await self.session.execute(
                select(User.referrer_id).where(User.id == current_id)
            )
            current_id = res.scalar_one_or_none()
            if current_id is None:
                break
            chain.append(current_id)
        return chain

    async def count_referrals_by_level(self, user_id: int) -> dict[int, int]:
        """Возвращает {1: N1, 2: N2, 3: N3}."""
        result: dict[int, int] = {1: 0, 2: 0, 3: 0}

        # уровень 1
        res1 = await self.session.execute(
            select(User.id).where(User.referrer_id == user_id)
        )
        l1 = [row[0] for row in res1]
        result[1] = len(l1)
        if not l1:
            return result

        # уровень 2
        res2 = await self.session.execute(
            select(User.id).where(User.referrer_id.in_(l1))
        )
        l2 = [row[0] for row in res2]
        result[2] = len(l2)
        if not l2:
            return result

        # уровень 3
        res3 = await self.session.execute(
            select(func.count(User.id)).where(User.referrer_id.in_(l2))
        )
        result[3] = int(res3.scalar_one())
        return result
