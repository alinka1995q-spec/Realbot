from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.bot_client import get_bot
from src.admin.deps import get_session, templates
from src.database.models import DepositStatus
from src.database.repositories import (
    AdminsRepo,
    DepositsRepo,
    PayoutsRepo,
    UsersRepo,
)
from src.i18n import i18n
from src.services.deposit_service import DepositService

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_deposits(
    request: Request,
    status: str = "pending",
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        ds = DepositStatus(status)
    except ValueError:
        ds = DepositStatus.PENDING
    items = await DepositsRepo(session).list_by_status(ds, limit=200)
    users_map = {}
    for d in items:
        u = await UsersRepo(session).get_by_id(d.user_id)
        if u:
            users_map[d.user_id] = u
    return templates.TemplateResponse(
        "deposits.html",
        {
            "request": request,
            "active_page": "deposits",
            "items": items,
            "users_map": users_map,
            "current_status": ds.value,
            "statuses": [s.value for s in DepositStatus],
        },
    )


@router.get("/{deposit_id}", response_class=HTMLResponse)
async def view_deposit(
    request: Request,
    deposit_id: int,
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    d = await DepositsRepo(session).get(deposit_id)
    if d is None:
        return RedirectResponse("/deposits", status_code=303)
    user = await UsersRepo(session).get_by_id(d.user_id)
    payouts = await PayoutsRepo(session).list_for_deposit(deposit_id)
    return templates.TemplateResponse(
        "deposit_view.html",
        {
            "request": request,
            "active_page": "deposits",
            "d": d,
            "user": user,
            "payouts": payouts,
        },
    )


@router.post("/{deposit_id}/confirm")
async def confirm_deposit(
    deposit_id: int,
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    bot = get_bot()
    svc = DepositService(session, bot)
    deposit = await svc.confirm(deposit_id, admin_data["admin_id"])
    await AdminsRepo(session).log(
        admin_data["admin_id"],
        "deposit_confirm",
        target_type="deposit",
        target_id=deposit_id,
        ip=admin_data.get("ip"),
    )
    # уведомление пользователю
    if deposit is not None:
        from src.utils.format import deposit_start_display, fmt_amount, fmt_date, fmt_dt

        user = await UsersRepo(session).get_by_id(deposit.user_id)
        payouts = await PayoutsRepo(session).list_for_deposit(deposit.id)
        cur = i18n.t("cur.default", user.lang) if user else "сом"
        if user:
            try:
                from src.keyboards.common import home_kb as _home_kb
                from src.database.repositories import SettingsRepo

                await bot.send_message(
                    user.telegram_id,
                    i18n.t(
                        "deposit.confirmed", user.lang,
                        id=deposit.id, amount=fmt_amount(deposit.amount), cur=cur,
                        tariff=deposit.tariff.name if deposit.tariff else "?",
                        start=fmt_date(deposit_start_display(deposit)),
                        end=fmt_date(deposit.ends_at),
                        count=len(payouts),
                        payout=fmt_amount(payouts[0].amount) if payouts else "0",
                        first_payout=fmt_dt(payouts[0].due_at) if payouts else "—",
                    ),
                    reply_markup=_home_kb(user.lang),
                )

                inv_url = (
                    await SettingsRepo(session).get("investors_group_url", "")
                    or await SettingsRepo(session).get("investors_group_invite", "")
                )
                if inv_url:
                    from src.middlewares.subscription import SubscriptionMiddleware
                    mw = SubscriptionMiddleware()
                    kb = mw._build_keyboard(user.lang, "", "", inv_url)
                    await bot.send_message(
                        user.telegram_id,
                        i18n.t("subscribe.required.title", user.lang),
                        reply_markup=kb,
                    )
            except Exception:
                pass
    return RedirectResponse(f"/deposits/{deposit_id}", status_code=303)


@router.post("/{deposit_id}/reject")
async def reject_deposit(
    deposit_id: int,
    reason: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    bot = get_bot()
    svc = DepositService(session, bot)
    deposit = await svc.reject(deposit_id, admin_data["admin_id"], reason or "—")
    if deposit is not None:
        user = await UsersRepo(session).get_by_id(deposit.user_id)
        if user:
            try:
                from src.keyboards.common import home_kb as _home_kb
                await bot.send_message(
                    user.telegram_id,
                    i18n.t("deposit.rejected", user.lang, id=deposit.id, reason=reason or "—"),
                    reply_markup=_home_kb(user.lang),
                )
            except Exception:
                pass
    return RedirectResponse(f"/deposits/{deposit_id}", status_code=303)


@router.post("/{deposit_id}/cancel")
async def cancel_deposit(
    deposit_id: int,
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    svc = DepositService(session, get_bot())
    await svc.cancel(deposit_id, admin_data["admin_id"])
    return RedirectResponse(f"/deposits/{deposit_id}", status_code=303)


@router.post("/{deposit_id}/requisites")
async def edit_deposit_requisites(
    deposit_id: int,
    payout_bank: str = Form(""),
    payout_number: str = Form(""),
    payout_full_name: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    fields: dict = {}
    if payout_bank.strip():
        fields["payout_bank"] = payout_bank.strip()
    if payout_number.strip():
        fields["payout_number"] = payout_number.strip()
    if payout_full_name.strip():
        fields["payout_full_name"] = payout_full_name.strip()
    if fields:
        await DepositsRepo(session).update_fields(deposit_id, **fields)
        await AdminsRepo(session).log(
            admin_data["admin_id"],
            "deposit_requisites_edit",
            target_type="deposit",
            target_id=deposit_id,
            payload=fields,
            ip=admin_data.get("ip"),
        )
    return RedirectResponse(f"/deposits/{deposit_id}", status_code=303)
