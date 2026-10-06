import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Broadcast,
    BroadcastStatus,
    Deposit,
    DepositStatus,
    User,
)
from src.database.repositories import BroadcastsRepo

logger = logging.getLogger(__name__)


class BroadcastService:
    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot
        self.repo = BroadcastsRepo(session)

    async def get_audience_ids(self, audience: str, payload: Optional[dict]) -> list[int]:
        if audience == "all":
            stmt = select(User.telegram_id).where(User.is_blocked.is_(False))
        elif audience == "active":
            stmt = select(User.telegram_id).where(
                User.is_blocked.is_(False),
                User.last_active_at.is_not(None),
            )
        elif audience == "with_deposit":
            stmt = (
                select(User.telegram_id)
                .join(Deposit, Deposit.user_id == User.id)
                .where(
                    User.is_blocked.is_(False),
                    Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value]),
                )
                .distinct()
            )
        elif audience == "without_deposit":
            stmt = (
                select(User.telegram_id)
                .where(
                    User.is_blocked.is_(False),
                    ~User.id.in_(
                        select(Deposit.user_id).where(
                            Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value])
                        )
                    ),
                )
            )
        elif audience == "by_tariff" and payload and payload.get("tariff_id"):
            stmt = (
                select(User.telegram_id)
                .join(Deposit, Deposit.user_id == User.id)
                .where(
                    User.is_blocked.is_(False),
                    Deposit.tariff_id == payload["tariff_id"],
                    Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value]),
                )
                .distinct()
            )
        else:
            stmt = select(User.telegram_id).where(User.is_blocked.is_(False))
        res = await self.session.execute(stmt)
        return [row[0] for row in res]

    async def run(self, broadcast_id: int) -> tuple[int, int]:
        b: Broadcast | None = await self.repo.get(broadcast_id)
        if b is None or b.status not in {BroadcastStatus.SCHEDULED.value, BroadcastStatus.RUNNING.value}:
            return 0, 0

        ids = await self.get_audience_ids(b.audience, b.audience_payload)
        await self.repo.update_progress(
            broadcast_id,
            status=BroadcastStatus.RUNNING,
            total=len(ids),
            started_at=datetime.now(timezone.utc),
        )
        await self.session.commit()

        sent = 0
        failed = 0
        for chat_id in ids:
            try:
                await self._send_one(chat_id, b)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await self._send_one(chat_id, b)
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramAPIError:
                failed += 1
            except Exception as e:
                logger.exception("broadcast send err: %s", e)
                failed += 1
            await asyncio.sleep(0.05)  # ~20 msg/s
        await self.repo.update_progress(
            broadcast_id,
            status=BroadcastStatus.DONE,
            sent=sent,
            failed=failed,
            finished_at=datetime.now(timezone.utc),
        )
        await self.session.commit()
        return sent, failed

    async def _send_one(self, chat_id: int, b: Broadcast) -> None:
        from src.keyboards.common import home_kb

        kb = home_kb("ru")
        if b.media_type == "photo" and b.media_file_id:
            await self.bot.send_photo(chat_id, b.media_file_id, caption=b.text, reply_markup=kb)
        elif b.media_type == "video" and b.media_file_id:
            await self.bot.send_video(chat_id, b.media_file_id, caption=b.text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id, b.text or "", reply_markup=kb)
