import io
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.models import DepositStatus
from src.database.repositories import (
    DepositsRepo,
    PayoutsRepo,
    ReferralsRepo,
    UsersRepo,
    WithdrawalsRepo,
)

router = APIRouter()

# Бишкек = UTC+6 (без перехода на летнее время)
BISHKEK_OFFSET = timedelta(hours=6)


def _bishkek_today_start_utc() -> datetime:
    """Возвращает момент 00:00 текущего дня по Бишкеку в UTC."""
    now_utc = datetime.now(timezone.utc)
    bishkek_now = now_utc + BISHKEK_OFFSET
    bishkek_midnight = bishkek_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (bishkek_midnight - BISHKEK_OFFSET).replace(tzinfo=timezone.utc)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    users = UsersRepo(session)
    deposits = DepositsRepo(session)
    payouts = PayoutsRepo(session)
    refs = ReferralsRepo(session)
    wd = WithdrawalsRepo(session)
    now = datetime.now(timezone.utc)

    total_users = await users.count_total()
    new_d = await users.count_since(now - timedelta(days=1))
    new_w = await users.count_since(now - timedelta(days=7))
    new_m = await users.count_since(now - timedelta(days=30))
    active_d = await users.count_active_since(now - timedelta(days=1))
    active_w = await users.count_active_since(now - timedelta(days=7))

    active_dep = await deposits.count_by_status(DepositStatus.ACTIVE)
    pending_dep = await deposits.count_by_status(DepositStatus.PENDING)
    completed_dep = await deposits.count_by_status(DepositStatus.COMPLETED)
    sum_active = await deposits.sum_active()
    sum_payouts = await payouts.sum_paid()
    sum_refs = await refs.sum_total()
    sum_wd = await wd.sum_paid()

    today_start = _bishkek_today_start_utc()
    sum_deposits_total = await deposits.sum_confirmed_total()
    sum_deposits_today = await deposits.sum_confirmed_since(today_start)
    sum_payouts_today = await payouts.sum_paid_since(today_start)
    sum_refs_today = await refs.sum_since(today_start)
    sum_wd_today = await wd.sum_paid_since(today_start)
    bishkek_now = (datetime.now(timezone.utc) + BISHKEK_OFFSET).strftime("%d.%m.%Y %H:%M")

    deps_by_day = await deposits.deposits_by_day(30)
    pays_by_day = await payouts.payouts_by_day(30)

    top = await refs.top_referrers(limit=10)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard",
            "stats": {
                "total_users": total_users,
                "new_d": new_d,
                "new_w": new_w,
                "new_m": new_m,
                "active_d": active_d,
                "active_w": active_w,
                "active_dep": active_dep,
                "pending_dep": pending_dep,
                "completed_dep": completed_dep,
                "sum_active": sum_active,
                "sum_payouts": sum_payouts,
                "sum_refs": sum_refs,
                "sum_wd": sum_wd,
                "sum_deposits_total": sum_deposits_total,
                "sum_deposits_today": sum_deposits_today,
                "sum_payouts_today": sum_payouts_today,
                "sum_refs_today": sum_refs_today,
                "sum_wd_today": sum_wd_today,
                "bishkek_now": bishkek_now,
            },
            "deps_by_day": deps_by_day,
            "pays_by_day": pays_by_day,
            "top_referrers": top,
        },
    )


def _render_chart(xs: list, ys: list, title: str, color: str = "#6366f1") -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": ["DejaVu Sans", "Arial", "sans-serif"],
        "font.size": 12,
        "axes.titlesize": 16,
        "axes.titleweight": "bold",
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "text.antialiased": True,
        "figure.dpi": 110,
        "savefig.dpi": 110,
    })

    fig, ax = plt.subplots(figsize=(11, 4), facecolor="#0f172a", dpi=110)
    ax.set_facecolor("#0f172a")
    if xs and ys:
        ax.plot(xs, ys, color=color, linewidth=2.4, marker="o", markersize=5)
        ax.fill_between(xs, ys, alpha=0.25, color=color)
    ax.grid(True, linestyle="--", alpha=0.2, color="#334155")
    ax.tick_params(axis="y", colors="#e2e8f0")
    ax.tick_params(axis="x", labelbottom=False, bottom=False)
    for s in ax.spines.values():
        s.set_color("#334155")
    ax.set_title(title, color="#e2e8f0", pad=12)
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", facecolor="#0f172a", bbox_inches="tight", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# простой in-memory кеш PNG-чартов
_CHART_CACHE: dict[str, tuple[float, bytes]] = {}
_CHART_TTL = 60  # 1 минута


def _cached_chart(key: str, builder) -> bytes:
    import time

    now = time.time()
    item = _CHART_CACHE.get(key)
    if item and now - item[0] < _CHART_TTL:
        return item[1]
    data = builder()
    _CHART_CACHE[key] = (now, data)
    return data


def _png_response(data: bytes) -> Response:
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=60"},  # кеш в браузере 1 минута
    )


def _aggregate_by_day(items: list, dt_attr: str, days: int = 30) -> tuple[list[str], list[int], dict[str, float]]:
    """Группирует по YYYY-MM-DD за последние N дней."""
    from collections import defaultdict
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts: dict[str, int] = defaultdict(int)
    sums: dict[str, float] = defaultdict(float)
    for it in items:
        dt = getattr(it, dt_attr)
        if not dt or dt < cutoff:
            continue
        key = dt.strftime("%Y-%m-%d")
        counts[key] += 1
        if hasattr(it, "amount") and it.amount is not None:
            sums[key] += float(it.amount)
    xs = sorted(counts.keys())
    ys = [counts[x] for x in xs]
    return xs, ys, sums


@router.get("/charts/users.png")
async def chart_users(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import select

    from src.database.models import User

    res = await session.execute(select(User))
    users = list(res.scalars())
    xs, ys, _sums = _aggregate_by_day(users, "created_at", days=30)
    data = _cached_chart(
        f"users:{len(xs)}:{sum(ys)}",
        lambda: _render_chart(xs, ys, "Регистрации (30 дней)", "#6366f1"),
    )
    return _png_response(data)


def _ensure_30_days(xs: list[str], ys: list[int]) -> tuple[list[str], list[int]]:
    """Заполняет пропуски нулями за последние 30 дней."""
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
    labels = [d.strftime("%d.%m") for d in days]
    src = {k: v for k, v in zip(xs, ys)}
    values = [src.get(d.strftime("%Y-%m-%d"), 0) for d in days]
    return labels, values


@router.get("/charts/data")
async def chart_data(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """JSON-данные за 30 дней для живых графиков (Chart.js)."""
    from sqlalchemy import select

    from src.database.models import Deposit, DepositStatus, Payout, PayoutStatus, User

    res = await session.execute(select(User))
    users_xs, users_ys, _ = _aggregate_by_day(list(res.scalars()), "created_at", days=30)
    u_labels, u_values = _ensure_30_days(users_xs, users_ys)

    res = await session.execute(
        select(Deposit).where(
            Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value])
        )
    )
    dep_xs, dep_ys, _ = _aggregate_by_day(list(res.scalars()), "created_at", days=30)
    d_labels, d_values = _ensure_30_days(dep_xs, dep_ys)

    res = await session.execute(select(Payout).where(Payout.status == PayoutStatus.PAID.value))
    pay_xs, pay_ys, _ = _aggregate_by_day(list(res.scalars()), "paid_at", days=30)
    p_labels, p_values = _ensure_30_days(pay_xs, pay_ys)

    return {
        "labels": u_labels,
        "users": u_values,
        "deposits": d_values,
        "payouts": p_values,
    }


@router.get("/charts/deposits.png")
async def chart_deposits(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import select

    from src.database.models import Deposit, DepositStatus

    res = await session.execute(
        select(Deposit).where(
            Deposit.status.in_([DepositStatus.ACTIVE.value, DepositStatus.COMPLETED.value])
        )
    )
    deps = list(res.scalars())
    xs, ys, _sums = _aggregate_by_day(deps, "created_at", days=30)
    data = _cached_chart(
        f"deposits:{len(xs)}:{sum(ys)}",
        lambda: _render_chart(xs, ys, "Депозиты (30 дней)", "#22c55e"),
    )
    return _png_response(data)


@router.get("/charts/payouts.png")
async def chart_payouts(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import select

    from src.database.models import Payout, PayoutStatus

    res = await session.execute(select(Payout).where(Payout.status == PayoutStatus.PAID.value))
    items = list(res.scalars())
    xs, ys, _sums = _aggregate_by_day(items, "paid_at", days=30)
    data = _cached_chart(
        f"payouts:{len(xs)}:{sum(ys)}",
        lambda: _render_chart(xs, ys, "Выплаты (30 дней)", "#f59e0b"),
    )
    return _png_response(data)
