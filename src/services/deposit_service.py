"""Логика создания депозита, подтверждения, генерации графика выплат, отклонения."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    BalanceChangeReason,
    Deposit,
    DepositStatus,
    PayoutStatus,
    Tariff,
    TariffPeriod,
)
from src.database.repositories import (
    BalanceRepo,
    DepositsRepo,
    PayoutsRepo,
    ReferralsRepo,
    SettingsRepo,
    TariffsRepo,
    UsersRepo,
)
from src.i18n import i18n

logger = logging.getLogger(__name__)


def _calc_payout_amount(tariff: Tariff, body: Decimal) -> Decimal:
    if tariff.payout_fixed is not None:
        return Decimal(tariff.payout_fixed)
    if tariff.payout_percent is not None:
        return (body * Decimal(tariff.payout_percent) / Decimal(100)).quantize(Decimal("0.01"))
    return Decimal(0)


def calc_schedule(tariff: Tariff, body: Decimal, started_at: datetime) -> list[tuple[datetime, Decimal, int]]:
    """Возвращает [(due_at, amount, seq), ...]."""
    period = TariffPeriod(tariff.period)
    if period == TariffPeriod.DAILY:
        step = 1
    elif period == TariffPeriod.EVERY_N_DAYS:
        step = max(1, tariff.period_n_days or 1)
    elif period == TariffPeriod.AT_END:
        step = tariff.duration_days
    else:
        step = 1

    n_payouts = max(1, tariff.duration_days // step)
    payout_amount = _calc_payout_amount(tariff, body)

    schedule: list[tuple[datetime, Decimal, int]] = []
    for i in range(1, n_payouts + 1):
        due = started_at + timedelta(days=step * i)
        schedule.append((due, payout_amount, i))
    return schedule


class DepositService:
    def __init__(self, session: AsyncSession, bot: Optional[Bot] = None) -> None:
        self.session = session
        self.bot = bot
        self.deposits = DepositsRepo(session)
        self.payouts = PayoutsRepo(session)
        self.tariffs = TariffsRepo(session)
        self.users = UsersRepo(session)
        self.referrals = ReferralsRepo(session)
        self.balance = BalanceRepo(session)
        self.settings = SettingsRepo(session)

    async def confirm(self, deposit_id: int, admin_id: Optional[int]) -> Optional[Deposit]:
        from src.database.repositories.admins import valid_admin_id

        deposit = await self.deposits.get(deposit_id)
        if deposit is None or deposit.status != DepositStatus.PENDING.value:
            return None
        tariff = deposit.tariff
        if tariff is None:
            tariff = await self.tariffs.get(deposit.tariff_id)
        admin_id = await valid_admin_id(self.session, admin_id)
        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(days=tariff.duration_days)

        # обновляем депозит
        await self.deposits.update_fields(
            deposit_id,
            status=DepositStatus.ACTIVE.value,
            started_at=now,
            ends_at=ends_at,
            confirmed_by_admin_id=admin_id,
        )

        # график выплат
        schedule = calc_schedule(tariff, Decimal(deposit.amount), now)
        items = [
            {
                "deposit_id": deposit.id,
                "user_id": deposit.user_id,
                "amount": amount,
                "due_at": due,
                "status": PayoutStatus.PENDING.value,
                "seq": seq,
            }
            for (due, amount, seq) in schedule
        ]
        if items:
            await self.payouts.bulk_create(items)

        # реферальные начисления
        await self._accrue_referrals(deposit)

        await self.session.flush()
        return await self.deposits.get(deposit_id)

    async def reject(self, deposit_id: int, admin_id: Optional[int], reason: str) -> Optional[Deposit]:
        from src.database.repositories.admins import valid_admin_id

        d = await self.deposits.get(deposit_id)
        if d is None or d.status != DepositStatus.PENDING.value:
            return None
        admin_id = await valid_admin_id(self.session, admin_id)
        await self.deposits.update_fields(
            deposit_id,
            status=DepositStatus.REJECTED.value,
            rejected_reason=reason,
            confirmed_by_admin_id=admin_id,
        )
        return await self.deposits.get(deposit_id)

    async def cancel(self, deposit_id: int, admin_id: Optional[int]) -> Optional[Deposit]:
        from src.database.repositories.admins import valid_admin_id

        d = await self.deposits.get(deposit_id)
        if d is None:
            return None
        admin_id = await valid_admin_id(self.session, admin_id)
        await self.deposits.update_fields(
            deposit_id,
            status=DepositStatus.CANCELLED.value,
            confirmed_by_admin_id=admin_id,
        )
        # отменяем будущие выплаты
        for p in await self.payouts.list_for_deposit(deposit_id):
            if p.status == PayoutStatus.PENDING.value:
                await self.payouts.mark_cancelled(p.id)
        return await self.deposits.get(deposit_id)

    async def _accrue_referrals(self, deposit: Deposit) -> None:
        chain = await self.users.referrer_chain(deposit.user_id, depth=3)
        if not chain:
            return
        p1, p2, p3 = await self.settings.get_ref_percents()
        percents = [p1, p2, p3]
        from_user = await self.users.get_by_id(deposit.user_id)
        from_label = (
            f"@{from_user.username}" if from_user and from_user.username
            else (from_user.full_name if from_user else f"id:{deposit.user_id}")
        )
        for i, ref_id in enumerate(chain):
            level = i + 1
            percent = percents[i]
            if percent <= 0:
                continue
            amount = (Decimal(deposit.amount) * percent / Decimal(100)).quantize(Decimal("0.01"))
            if amount <= 0:
                continue
            earning = await self.referrals.add_earning(
                to_user_id=ref_id,
                from_user_id=deposit.user_id,
                deposit_id=deposit.id,
                level=level,
                percent=percent,
                amount=amount,
            )
            await self.users.add_to_balance(ref_id, amount)
            await self.balance.add(
                user_id=ref_id,
                amount=amount,
                reason=BalanceChangeReason.REFERRAL,
                ref_id=earning.id,
                comment=f"Реферал L{level} от пользователя #{deposit.user_id}",
            )
            # уведомления реферера: бонус
            if self.bot is not None:
                ref_user = await self.users.get_by_id(ref_id)
                if ref_user:
                    try:
                        from src.keyboards.common import home_kb

                        await self.bot.send_message(
                            ref_user.telegram_id,
                            i18n.t(
                                "referrals.notify_bonus",
                                ref_user.lang,
                                amount=str(amount),
                                cur=i18n.t("cur.default", ref_user.lang),
                                level=level,
                                from_user=from_label,
                            ),
                            reply_markup=home_kb(ref_user.lang),
                        )
                    except TelegramAPIError as e:
                        logger.warning("notify ref bonus to %s failed: %s", ref_user.telegram_id, e)
