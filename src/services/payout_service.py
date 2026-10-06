"""Обработка выплат: автоматическое наступление, ручное подтверждение админом, уведомления."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    BalanceChangeReason,
    DepositStatus,
    PayoutStatus,
)
from src.database.repositories import (
    BalanceRepo,
    DepositsRepo,
    PayoutsRepo,
    UsersRepo,
)
from src.i18n import i18n

logger = logging.getLogger(__name__)


class PayoutService:
    def __init__(self, session: AsyncSession, bot: Optional[Bot] = None) -> None:
        self.session = session
        self.bot = bot
        self.payouts = PayoutsRepo(session)
        self.deposits = DepositsRepo(session)
        self.users = UsersRepo(session)
        self.balance = BalanceRepo(session)

    async def mark_paid(self, payout_id: int, admin_id: Optional[int]) -> bool:
        payout = await self.payouts.get_with_deposit(payout_id)
        if payout is None or payout.status != PayoutStatus.PENDING.value:
            return False

        await self.payouts.mark_paid(payout_id, admin_id)
        # Деньги выплачиваются напрямую на карту пользователя.
        # На внутренний баланс попадают ТОЛЬКО реферальные начисления.

        # уведомление
        if self.bot:
            try:
                user = await self.users.get_by_id(payout.user_id)
                if user:
                    from src.keyboards.common import home_kb

                    await self.bot.send_message(
                        user.telegram_id,
                        i18n.t(
                            "payout.notify_paid",
                            user.lang,
                            dep=payout.deposit_id,
                            amount=str(payout.amount),
                            cur=i18n.t("cur.default", user.lang),
                        ),
                        reply_markup=home_kb(user.lang),
                    )
            except TelegramAPIError as e:
                logger.warning("Failed to notify payout %s: %s", payout_id, e)

        # автозавершение депозита если все выплаты исполнены
        await self._maybe_complete_deposit(payout.deposit_id)
        return True

    async def _maybe_complete_deposit(self, deposit_id: int) -> None:
        payouts = await self.payouts.list_for_deposit(deposit_id)
        if all(p.status != PayoutStatus.PENDING.value for p in payouts):
            d = await self.deposits.get(deposit_id)
            if d is None or d.status == DepositStatus.COMPLETED.value:
                return
            await self.deposits.update_fields(deposit_id, status=DepositStatus.COMPLETED.value)
            # уведомление админам
            if self.bot:
                from src.services.notifications import notify_admins
                u = await self.users.get_by_id(d.user_id)
                user_label = (
                    f"@{u.username}" if u and u.username
                    else (u.full_name if u else f"#{d.user_id}")
                )
                await notify_admins(
                    self.bot,
                    self.session,
                    f"🏁 <b>Депозит #{deposit_id} завершён</b>\n\n"
                    f"👤 {user_label}\n"
                    f"💵 Сумма: {d.amount}\n"
                    f"📋 Тариф: {d.tariff.name if d.tariff else '?'}",
                )

    async def auto_process_due(self) -> int:
        """Помечает все наступившие выплаты как PAID. Возвращает количество."""
        due = await self.payouts.due_pending(datetime.now(timezone.utc))
        count = 0
        for p in due:
            ok = await self.mark_paid(p.id, admin_id=None)
            if ok:
                count += 1
        return count
