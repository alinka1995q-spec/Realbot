from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models import Payout, User
from src.i18n import i18n
from src.keyboards.common import back_kb
from src.utils.format import fmt_amount, fmt_date, payout_status_label

router = Router(name="payout")


@router.callback_query(F.data == "menu:payouts")
async def my_payouts(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    res = await session.execute(
        select(Payout)
        .options(joinedload(Payout.deposit))
        .where(Payout.user_id == db_user.id)
        .order_by(Payout.due_at.desc())
        .limit(30)
    )
    items = list(res.scalars())
    cur = i18n.t("cur.default", db_user.lang)
    if not items:
        await cb.message.edit_text(
            i18n.t("payout.list_empty", db_user.lang), reply_markup=back_kb(db_user.lang)
        )
        await cb.answer()
        return
    lines = ["💸 <b>Мои выплаты</b>", ""]
    for p in items:
        lines.append(
            i18n.t(
                "payout.list_item",
                db_user.lang,
                id=p.id,
                dep=p.deposit_id,
                amount=fmt_amount(p.amount),
                cur=cur,
                status=payout_status_label(p.status, db_user.lang),
                date=fmt_date(p.paid_at or p.due_at),
            )
        )
    await cb.message.edit_text("\n".join(lines), reply_markup=back_kb(db_user.lang))
    await cb.answer()
