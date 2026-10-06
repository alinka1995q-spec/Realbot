"""Catch-all для непонятных сообщений: показывает подсказку и главное меню."""

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User
from src.database.repositories import SettingsRepo
from src.i18n import i18n
from src.keyboards.common import main_menu_kb

router = Router(name="fallback")


@router.message(F.text)
async def unknown_message(
    msg: Message, session: AsyncSession, db_user: User, is_admin: bool
) -> None:
    """Срабатывает только если ни один другой handler не обработал сообщение."""
    contact = (await SettingsRepo(session).get("support_username", "")) or "—"
    await msg.answer(
        i18n.t("common.unknown", db_user.lang, contact=contact),
        reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
    )
