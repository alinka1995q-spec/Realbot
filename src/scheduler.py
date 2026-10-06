"""Фоновые задачи: автоматические выплаты, отправка отложенных рассылок, завершение депозитов."""

import logging
from datetime import datetime, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.database import async_session_factory
from src.database.repositories import BroadcastsRepo
from src.services.backup import run_backup
from src.services.broadcast_service import BroadcastService
from src.services.payout_service import PayoutService

logger = logging.getLogger(__name__)


async def _process_payouts_job(bot: Bot) -> None:
    async with async_session_factory() as session:
        svc = PayoutService(session, bot)
        count = await svc.auto_process_due()
        await session.commit()
        if count:
            logger.info("auto payouts processed: %s", count)


async def _process_broadcasts_job(bot: Bot) -> None:
    async with async_session_factory() as session:
        repo = BroadcastsRepo(session)
        due = await repo.due(datetime.now(timezone.utc))
        for b in due:
            svc = BroadcastService(session, bot)
            try:
                await svc.run(b.id)
            except Exception as e:
                logger.exception("broadcast %s failed: %s", b.id, e)


async def _backup_job() -> None:
    path = await run_backup()
    if path:
        logger.info("Backup OK: %s", path)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_process_payouts_job, IntervalTrigger(minutes=1), args=[bot])
    scheduler.add_job(_process_broadcasts_job, IntervalTrigger(minutes=1), args=[bot])
    # ежедневный бэкап в 03:00 по таймзоне
    scheduler.add_job(_backup_job, CronTrigger(hour=3, minute=0))
    return scheduler
