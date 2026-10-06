from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.models import (
    BalanceChangeReason,
    Deposit,
    DepositStatus,
    User,
    UserChatMessage,
)
from src.database.repositories import (
    AdminsRepo,
    BalanceRepo,
    DepositsRepo,
    ReferralsRepo,
    UsersRepo,
    WithdrawalsRepo,
)

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    q: str = "",
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    users_repo = UsersRepo(session)
    if q.strip():
        items = await users_repo.search(q.strip().lstrip("@"), limit=100)
    else:
        res = await session.execute(select(User).order_by(User.created_at.desc()).limit(50))
        items = list(res.scalars())
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "active_page": "users", "items": items, "q": q},
    )


@router.get("/{uid}", response_class=HTMLResponse)
async def view_user(
    request: Request,
    uid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    u = await UsersRepo(session).get_by_id(uid)
    if u is None:
        return RedirectResponse("/users", status_code=303)
    deposits = await DepositsRepo(session).list_user(uid, limit=30)
    withdrawals = await WithdrawalsRepo(session).list_user(uid, limit=30)
    referrals = await ReferralsRepo(session).list_for_user(uid, limit=30)
    levels = await UsersRepo(session).count_referrals_by_level(uid)
    balance_log = await BalanceRepo(session).list_user(uid, limit=50)
    return templates.TemplateResponse(
        "user_view.html",
        {
            "request": request,
            "active_page": "users",
            "u": u,
            "deposits": deposits,
            "withdrawals": withdrawals,
            "referrals": referrals,
            "levels": levels,
            "balance_log": balance_log,
        },
    )


@router.post("/{uid}/balance")
async def adjust_balance(
    uid: int,
    amount: Decimal = Form(...),
    comment: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await UsersRepo(session).add_to_balance(uid, amount)
    await BalanceRepo(session).add(
        user_id=uid,
        amount=amount,
        reason=BalanceChangeReason.MANUAL_CREDIT if amount >= 0 else BalanceChangeReason.MANUAL_DEBIT,
        admin_id=admin_data["admin_id"],
        comment=comment or None,
    )
    await AdminsRepo(session).log(
        admin_data["admin_id"],
        "balance_adjust",
        target_type="user",
        target_id=uid,
        payload={"amount": str(amount), "comment": comment},
        ip=admin_data.get("ip"),
    )
    return RedirectResponse(f"/users/{uid}", status_code=303)


@router.post("/{uid}/profile")
async def edit_profile(
    uid: int,
    full_name: str = Form(""),
    phone: str = Form(""),
    lang: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Редактирование базовых полей пользователя."""
    fields: dict = {}
    if full_name.strip():
        fields["full_name"] = full_name.strip()
    if phone.strip():
        fields["phone"] = phone.strip()
    if lang in ("ru", "kg"):
        fields["lang"] = lang
    if fields:
        await session.execute(update(User).where(User.id == uid).values(**fields))
        await AdminsRepo(session).log(
            admin_data["admin_id"],
            "user_profile_edit",
            target_type="user",
            target_id=uid,
            payload=fields,
            ip=admin_data.get("ip"),
        )
    return RedirectResponse(f"/users/{uid}", status_code=303)


@router.post("/{uid}/requisites")
async def edit_all_requisites(
    uid: int,
    payout_bank: str = Form(""),
    payout_number: str = Form(""),
    payout_full_name: str = Form(""),
    scope: str = Form("active"),  # active | all
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет реквизиты на всех депозитах пользователя.
    scope=active — только pending+active, scope=all — все.
    """
    fields: dict = {}
    if payout_bank.strip():
        fields["payout_bank"] = payout_bank.strip()
    if payout_number.strip():
        fields["payout_number"] = payout_number.strip()
    if payout_full_name.strip():
        fields["payout_full_name"] = payout_full_name.strip()
    if fields:
        stmt = update(Deposit).where(Deposit.user_id == uid)
        if scope == "active":
            stmt = stmt.where(
                Deposit.status.in_([DepositStatus.PENDING.value, DepositStatus.ACTIVE.value])
            )
        stmt = stmt.values(**fields)
        await session.execute(stmt)
        await AdminsRepo(session).log(
            admin_data["admin_id"],
            "user_requisites_edit",
            target_type="user",
            target_id=uid,
            payload={**fields, "scope": scope},
            ip=admin_data.get("ip"),
        )
    return RedirectResponse(f"/users/{uid}", status_code=303)


@router.post("/{uid}/block")
async def toggle_block(
    uid: int,
    reason: str = Form(""),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    u = await UsersRepo(session).get_by_id(uid)
    if u:
        await UsersRepo(session).set_blocked(uid, not u.is_blocked, reason=reason or None)
    return RedirectResponse(f"/users/{uid}", status_code=303)


@router.get("/{uid}/chat", response_class=HTMLResponse)
async def view_chat(
    request: Request,
    uid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    u = await UsersRepo(session).get_by_id(uid)
    if u is None:
        return RedirectResponse("/users", status_code=303)
    res = await session.execute(
        select(UserChatMessage)
        .where(UserChatMessage.user_id == uid)
        .order_by(UserChatMessage.created_at.desc())
        .limit(200)
    )
    msgs = list(res.scalars())
    msgs.reverse()
    return templates.TemplateResponse(
        "user_chat.html",
        {"request": request, "active_page": "users", "u": u, "messages": msgs},
    )
