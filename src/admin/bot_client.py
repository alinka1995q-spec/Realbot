"""Общий aiogram-Bot для веб-админки.

Используется чтобы при действиях из веб-панели (подтверждение депозита/вывода,
ручная отметка выплаты) отправлять уведомления пользователям в Telegram.
"""

from functools import lru_cache

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings


@lru_cache(maxsize=1)
def get_bot() -> Bot:
    settings = get_settings()
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
