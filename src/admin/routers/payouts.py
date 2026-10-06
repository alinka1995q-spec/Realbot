from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.bot_client import get_bot
from src.admin.deps import get_session, templates
from src.database.models import PayoutStatus
from src.database.repositories import DepositsRepo, PayoutsRepo, UsersRepo
from src.services.payout_service import PayoutService

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_payouts(
    request: Request,
    period: str = "today",
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """period: today / tomorrow / overdue / all_pending / paid / cancelled."""
    repo = PayoutsRepo(session)
    # Считаем дни по часовому поясу Бишкека (UTC+6)
    BISHKEK = timezone(timedelta(hours=6))
    now_bk = datetime.now(BISHKEK)
    today_start_bk = now_bk.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_bk.astimezone(timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    day_after = today_start + timedelta(days=2)

    if period == "today":
        items = await repo.list_pending_in_range(today_start, tomorrow_start)
    elif period == "tomorrow":
        items = await repo.list_pending_in_range(tomorrow_start, day_after)
    elif period == "overdue":
        items = await repo.list_pending_overdue(today_start)
    elif period == "paid":
        items = await repo.list_by_status(PayoutStatus.PAID, limit=200)
    elif period == "cancelled":
        items = await repo.list_by_status(PayoutStatus.CANCELLED, limit=200)
    else:  # all_pending
        items = await repo.list_by_status(PayoutStatus.PENDING, limit=500)

    users_map = {}
    for p in items:
        u = await UsersRepo(session).get_by_id(p.user_id)
        if u:
            users_map[p.user_id] = u

    return templates.TemplateResponse(
        "payouts.html",
        {
            "request": request,
            "active_page": "payouts",
            "items": items,
            "users_map": users_map,
            "period": period,
        },
    )


@router.post("/{payout_id}/mark-paid")
async def mark_paid(
    payout_id: int,
    period: str = Form("today"),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    svc = PayoutService(session, bot=get_bot())
    await svc.mark_paid(payout_id, admin_data["admin_id"])
    return RedirectResponse(f"/payouts?period={period}", status_code=303)


@router.post("/{payout_id}/edit-requisites")
async def edit_requisites(
    payout_id: int,
    payout_bank: str = Form(""),
    payout_number: str = Form(""),
    payout_full_name: str = Form(""),
    period: str = Form("today"),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет реквизиты у депозита, к которому привязана эта выплата."""
    p = await PayoutsRepo(session).get_with_deposit(payout_id)
    if p is None or p.deposit is None:
        return RedirectResponse(f"/payouts?period={period}", status_code=303)
    fields = {}
    if payout_bank.strip():
        fields["payout_bank"] = payout_bank.strip()
    if payout_number.strip():
        fields["payout_number"] = payout_number.strip()
    if payout_full_name.strip():
        fields["payout_full_name"] = payout_full_name.strip()
    if fields:
        await DepositsRepo(session).update_fields(p.deposit_id, **fields)
    return RedirectResponse(f"/payouts?period={period}", status_code=303)
