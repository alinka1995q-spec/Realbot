from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.bot_client import get_bot
from src.admin.deps import get_session, templates
from src.database.models import WithdrawalStatus
from src.database.repositories import UsersRepo, WithdrawalsRepo
from src.services.withdrawal_service import WithdrawalService

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_withdrawals(
    request: Request,
    status: str = "pending",
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        ws = WithdrawalStatus(status)
    except ValueError:
        ws = WithdrawalStatus.PENDING
    items = await WithdrawalsRepo(session).list_by_status(ws, limit=200)
    users_map = {}
    for w in items:
        u = await UsersRepo(session).get_by_id(w.user_id)
        if u:
            users_map[w.user_id] = u
    return templates.TemplateResponse(
        "withdrawals.html",
        {
            "request": request,
            "active_page": "withdrawals",
            "items": items,
            "users_map": users_map,
            "current_status": ws.value,
            "statuses": [s.value for s in WithdrawalStatus],
        },
    )


@router.post("/{wid}/approve")
async def approve(
    wid: int,
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await WithdrawalService(session, bot=get_bot()).approve(wid, admin_data["admin_id"])
    return RedirectResponse("/withdrawals", status_code=303)


@router.post("/{wid}/reject")
async def reject(
    wid: int,
    reason: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await WithdrawalService(session, bot=get_bot()).reject(wid, admin_data["admin_id"], reason or "—")
    return RedirectResponse("/withdrawals", status_code=303)
