"""Утилиты для отправки уведомлений администраторам и пользователям."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories import AdminsRepo

logger = logging.getLogger(__name__)


async def notify_admins(
    bot: Bot,
    session: AsyncSession,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = "HTML",
) -> int:
    """Отправляет text всем администраторам. Возвращает количество успешных доставок."""
    admins = await AdminsRepo(session).list_all()
    sent = 0
    for a in admins:
        try:
            await bot.send_message(
                a.telegram_id, text, reply_markup=reply_markup, parse_mode=parse_mode
            )
            sent += 1
        except TelegramAPIError as e:
            logger.warning("notify admin %s failed: %s", a.telegram_id, e)
        except Exception as e:
            logger.exception("notify admin %s error: %s", a.telegram_id, e)
    return sent


async def notify_user(
    bot: Bot, telegram_id: int, text: str, *, parse_mode: str | None = "HTML"
) -> bool:
    try:
        await bot.send_message(telegram_id, text, parse_mode=parse_mode)
        return True
    except TelegramAPIError as e:
        logger.warning("notify user %s failed: %s", telegram_id, e)
        return False
    except Exception as e:
        logger.exception("notify user %s error: %s", telegram_id, e)
        return False
