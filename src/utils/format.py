from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.database.models import (
    Deposit,
    DepositStatus,
    Payout,
    PayoutStatus,
    Tariff,
    TariffPeriod,
)
from src.i18n import i18n

# Часовой пояс Бишкека (UTC+6, без перехода на летнее время)
BISHKEK_TZ = timezone(timedelta(hours=6))


def _to_bishkek(dt: datetime) -> datetime:
    """Конвертирует datetime (aware или naive в UTC) в часовой пояс Бишкека."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BISHKEK_TZ)


def fmt_amount(value: Decimal | float | int | str | None) -> str:
    if value is None:
        return "0"
    try:
        d = Decimal(value)
    except Exception:
        return str(value)
    if d == d.to_integral():
        return f"{int(d):,}".replace(",", " ")
    return f"{d:,.2f}".replace(",", " ")


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return _to_bishkek(dt).strftime("%Y-%m-%d %H:%M")


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return _to_bishkek(dt).strftime("%Y-%m-%d")


_RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def fmt_date_human(dt: datetime | None) -> str:
    """13 мая 2026"""
    if dt is None:
        return "—"
    d = _to_bishkek(dt)
    return f"{d.day} {_RU_MONTHS[d.month - 1]} {d.year}"


def deposit_start_display(deposit) -> datetime | None:
    """День, с которого депозит начинает работать = следующий день после активации.

    Совпадает с днём первой выплаты для ежедневного тарифа и с тем,
    что админка показывает в колонке «Срок».
    """
    if deposit.started_at is None:
        return None
    return deposit.started_at + timedelta(days=1)


def tariff_schedule_label(t: Tariff, lang: str) -> str:
    p = TariffPeriod(t.period)
    if p == TariffPeriod.DAILY:
        return "ежедневно" if lang == "ru" else "күн сайын"
    if p == TariffPeriod.EVERY_N_DAYS:
        return f"раз в {t.period_n_days} дн." if lang == "ru" else f"{t.period_n_days} күнгө бир жолу"
    return "в конце срока" if lang == "ru" else "мөөнөттүн аягында"


def tariff_payout_label(t: Tariff) -> str:
    if t.payout_fixed is not None:
        return f"{fmt_amount(t.payout_fixed)}"
    if t.payout_percent is not None:
        return f"{_strip_trailing_zeros(t.payout_percent)}%"
    return "—"


def _strip_trailing_zeros(value) -> str:
    """12.0000 -> 12, 8.5000 -> 8.5"""
    from decimal import Decimal

    d = Decimal(str(value)).normalize()
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def deposit_status_label(status: str, lang: str) -> str:
    try:
        s = DepositStatus(status)
    except ValueError:
        return status
    return i18n.t(f"deposit.status.{s.value}", lang)


def payout_status_label(status: str, lang: str) -> str:
    try:
        s = PayoutStatus(status)
    except ValueError:
        return status
    return i18n.t(f"payout.status.{s.value}", lang)


def short_user(tg_id: int, username: str | None, full_name: str | None) -> str:
    parts = [f"id:{tg_id}"]
    if username:
        parts.insert(0, f"@{username}")
    if full_name:
        parts.append(full_name)
    return " · ".join(parts)
