from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User
from src.database.repositories import SettingsRepo
from src.i18n import i18n
from src.keyboards.common import back_kb

router = Router(name="support")


@router.callback_query(F.data == "menu:support")
async def show_support(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    contact = await SettingsRepo(session).get("support_username", "")
    text = (
        i18n.t("support.text", db_user.lang, contact=contact)
        if contact
        else i18n.t("support.no_contact", db_user.lang)
    )
    await cb.message.edit_text(text, reply_markup=back_kb(db_user.lang))
    await cb.answer()
