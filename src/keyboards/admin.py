from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.i18n import i18n


def admin_main_kb(lang: str, is_full_admin: bool = True) -> InlineKeyboardMarkup:
    """Полный admin видит всё, moderator — только депозиты."""
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("admin.menu.deposits", lang), callback_data="adm:deposits")
    if is_full_admin:
        b.button(text=i18n.t("admin.menu.payouts", lang), callback_data="adm:payouts")
        b.button(text=i18n.t("admin.menu.withdrawals", lang), callback_data="adm:withdrawals")
        b.button(text=i18n.t("admin.menu.tariffs", lang), callback_data="adm:tariffs")
        b.button(text=i18n.t("admin.menu.requisites", lang), callback_data="adm:requisites")
        b.button(text="🏦 Банки", callback_data="adm:banks")
        b.button(text=i18n.t("admin.menu.users", lang), callback_data="adm:users")
        b.button(text=i18n.t("admin.menu.referrals", lang), callback_data="adm:referrals")
        b.button(text=i18n.t("admin.menu.broadcast", lang), callback_data="adm:broadcast")
        b.button(text=i18n.t("admin.menu.stats", lang), callback_data="adm:stats")
        b.button(text=i18n.t("admin.menu.admins", lang), callback_data="adm:admins")
        b.button(text=i18n.t("admin.menu.texts", lang), callback_data="adm:texts")
        b.button(text="📢 Подписки", callback_data="adm:subs")
    b.button(text=i18n.t("common.back", lang), callback_data="menu:home")
    b.adjust(2)
    return b.as_markup()


def admin_deposit_actions_kb(deposit_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("admin.btn_confirm", lang), callback_data=f"adm:dep:ok:{deposit_id}")
    b.button(text=i18n.t("admin.btn_reject", lang), callback_data=f"adm:dep:no:{deposit_id}")
    b.button(text="✏️ Изменить данные", callback_data=f"adm:dep:edit:{deposit_id}")
    b.adjust(2, 1)
    return b.as_markup()


def confirm_action_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    """Двухкнопочная клавиатура подтверждения."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, подтвердить", callback_data=yes_cb)
    b.button(text="❌ Отмена", callback_data=no_cb)
    b.adjust(1)
    return b.as_markup()


def deposit_edit_kb(deposit_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏦 Банк", callback_data=f"adm:dep:setbank:{deposit_id}")
    b.button(text="💳 Номер", callback_data=f"adm:dep:setnum:{deposit_id}")
    b.button(text="👤 ФИО", callback_data=f"adm:dep:setfio:{deposit_id}")
    b.button(text="↩️ Назад", callback_data=f"adm:dep:show:{deposit_id}")
    b.adjust(1)
    return b.as_markup()


def admin_withdrawal_actions_kb(withdrawal_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("admin.btn_confirm", lang), callback_data=f"adm:wd:ok:{withdrawal_id}")
    b.button(text=i18n.t("admin.btn_reject", lang), callback_data=f"adm:wd:no:{withdrawal_id}")
    b.adjust(2)
    return b.as_markup()


def audience_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Всем", callback_data="adm:bc:aud:all")
    b.button(text="Активным", callback_data="adm:bc:aud:active")
    b.button(text="С депозитом", callback_data="adm:bc:aud:with_deposit")
    b.button(text="Без депозита", callback_data="adm:bc:aud:without_deposit")
    b.button(text=i18n.t("common.cancel", lang), callback_data="adm:menu")
    b.adjust(2, 2, 1)
    return b.as_markup()
