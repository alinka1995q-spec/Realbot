from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Часовой пояс Бишкека (UTC+6, без перехода на летнее время)
_BISHKEK = timezone(timedelta(hours=6))


def _bishkek_dt(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Конвертирует UTC-datetime в Бишкек и форматирует."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BISHKEK).strftime(fmt)


templates.env.filters["bk"] = _bishkek_dt
templates.env.filters["bk_date"] = lambda dt: _bishkek_dt(dt, "%Y-%m-%d")


# ------- Русские лейблы для статусов/типов -------
RU_LABELS: dict[str, dict[str, str]] = {
    "deposit_status": {
        "pending": "Ожидают",
        "active": "Активные",
        "completed": "Завершённые",
        "rejected": "Отклонённые",
        "cancelled": "Закрытые",
    },
    "payout_status": {
        "pending": "Ожидают",
        "paid": "Выплачено",
        "cancelled": "Отменено",
    },
    "withdrawal_status": {
        "pending": "Ожидают",
        "approved": "Одобрено",
        "rejected": "Отклонено",
    },
    "tariff_period": {
        "daily": "Ежедневно",
        "every_n_days": "Раз в N дней",
        "at_end": "В конце срока",
    },
    "broadcast_audience": {
        "all": "Всем",
        "active": "Активным",
        "with_deposit": "С депозитом",
        "without_deposit": "Без депозита",
        "by_tariff": "По тарифу",
    },
    "broadcast_status": {
        "scheduled": "Запланирована",
        "running": "В работе",
        "done": "Завершена",
        "failed": "Ошибка",
    },
    "admin_role": {
        "admin": "Админ",
        "moderator": "Модератор",
    },
    "media_type": {
        "photo": "Фото",
        "video": "Видео",
    },
}


def tr(category: str, code: str) -> str:
    """Возвращает русскую метку для статуса/типа. Если перевода нет — отдаёт исходную строку."""
    if not code:
        return "—"
    return RU_LABELS.get(category, {}).get(code, code)


templates.env.globals["tr"] = tr
templates.env.globals["RU_LABELS"] = RU_LABELS


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
