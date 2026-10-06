import logging
from decimal import Decimal
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import BalanceChangeReason, WithdrawalStatus
from src.database.repositories import (
    BalanceRepo,
    DepositsRepo,
    SettingsRepo,
    UsersRepo,
    WithdrawalsRepo,
)
from src.i18n import i18n

logger = logging.getLogger(__name__)


class WithdrawalService:
    def __init__(self, session: AsyncSession, bot: Optional[Bot] = None) -> None:
        self.session = session
        self.bot = bot
        self.withdrawals = WithdrawalsRepo(session)
        self.users = UsersRepo(session)
        self.balance = BalanceRepo(session)
        self.deposits = DepositsRepo(session)
        self.settings = SettingsRepo(session)

    async def request(
        self,
        *,
        user_id: int,
        amount: Decimal,
        bank: str,
        number: str,
        holder_name: Optional[str],
    ) -> tuple[bool, Optional[int], Optional[str]]:
        user = await self.users.get_by_id(user_id)
        if user is None:
            return False, None, "user not found"

        min_w = await self.settings.get_decimal("min_withdrawal", Decimal("0"))
        if amount < min_w:
            return False, None, "min"
        if Decimal(user.balance) < amount:
            return False, None, "no_funds"

        # требование активного депозита для рефовода
        require_active = await self.settings.get_bool("require_active_deposit_for_withdraw_ref", True)
        if require_active and not await self.deposits.has_any_confirmed(user_id):
            return False, None, "need_active"

        # списываем сразу с баланса (резервируем)
        await self.users.add_to_balance(user_id, -amount)
        w = await self.withdrawals.create(
            user_id=user_id,
            amount=amount,
            bank=bank,
            number=number,
            holder_name=holder_name,
        )
        await self.balance.add(
            user_id=user_id,
            amount=-amount,
            reason=BalanceChangeReason.WITHDRAWAL,
            ref_id=w.id,
            comment="Заявка на вывод",
        )
        return True, w.id, None

    async def approve(self, withdrawal_id: int, admin_id: Optional[int]) -> bool:
        w = await self.withdrawals.get(withdrawal_id)
        if w is None or w.status != WithdrawalStatus.PENDING.value:
            return False
        await self.withdrawals.set_status(withdrawal_id, WithdrawalStatus.APPROVED, admin_id=admin_id)
        if self.bot:
            try:
                user = await self.users.get_by_id(w.user_id)
                if user:
                    from src.keyboards.common import home_kb

                    await self.bot.send_message(
                        user.telegram_id,
                        i18n.t(
                            "withdrawal.approved",
                            user.lang,
                            id=w.id,
                            bank=w.bank,
                            number=w.number,
                        ),
                        reply_markup=home_kb(user.lang),
                    )
            except TelegramAPIError as e:
                logger.warning("notify approve withdrawal err: %s", e)
        return True

    async def reject(self, withdrawal_id: int, admin_id: Optional[int], reason: str) -> bool:
        w = await self.withdrawals.get(withdrawal_id)
        if w is None or w.status != WithdrawalStatus.PENDING.value:
            return False
        # возвращаем деньги
        await self.users.add_to_balance(w.user_id, Decimal(w.amount))
        await self.balance.add(
            user_id=w.user_id,
            amount=Decimal(w.amount),
            reason=BalanceChangeReason.ADJUSTMENT,
            ref_id=w.id,
            admin_id=admin_id,
            comment=f"Возврат по отклонённому выводу #{w.id}",
        )
        await self.withdrawals.set_status(
            withdrawal_id, WithdrawalStatus.REJECTED, admin_id=admin_id, rejected_reason=reason
        )
        if self.bot:
            try:
                user = await self.users.get_by_id(w.user_id)
                if user:
                    from src.keyboards.common import home_kb

                    await self.bot.send_message(
                        user.telegram_id,
                        i18n.t("withdrawal.rejected", user.lang, id=w.id, reason=reason),
                        reply_markup=home_kb(user.lang),
                    )
            except TelegramAPIError as e:
                logger.warning("notify reject withdrawal err: %s", e)
        return True
