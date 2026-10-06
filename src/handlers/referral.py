from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import User
from src.database.repositories import ReferralsRepo, SettingsRepo, UsersRepo
from src.i18n import i18n
from src.keyboards.common import back_kb
from src.utils.format import fmt_amount

router = Router(name="referral")


@router.callback_query(F.data == "menu:referrals")
async def show_referrals(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    users = UsersRepo(session)
    refs = ReferralsRepo(session)
    settings_repo = SettingsRepo(session)
    bot_settings = get_settings()

    p1, p2, p3 = await settings_repo.get_ref_percents()
    levels = await users.count_referrals_by_level(db_user.id)
    earned = await refs.sum_for_user(db_user.id)
    cur = i18n.t("cur.default", db_user.lang)

    common = dict(
        p1=p1, p2=p2, p3=p3,
        n1=levels.get(1, 0), n2=levels.get(2, 0), n3=levels.get(3, 0),
        earned=fmt_amount(earned), cur=cur,
    )

    if bot_settings.bot_username:
        ref_link = f"https://t.me/{bot_settings.bot_username}?start={db_user.id}"
        text = i18n.t("referrals.title", db_user.lang, link=ref_link, **common)
    else:
        text = i18n.t("referrals.title_no_link", db_user.lang, **common)

    await cb.message.edit_text(text, reply_markup=back_kb(db_user.lang))
    await cb.answer()
