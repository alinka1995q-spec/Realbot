from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from src.i18n import i18n


def main_menu_kb(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("menu.deposit", lang), callback_data="menu:new_deposit")
    b.button(text=i18n.t("menu.tariffs", lang), callback_data="menu:tariffs")
    b.button(text=i18n.t("menu.my_deposits", lang), callback_data="menu:my_deposits")
    b.button(text=i18n.t("menu.payouts", lang), callback_data="menu:payouts")
    b.button(text=i18n.t("menu.referrals", lang), callback_data="menu:referrals")
    b.button(text=i18n.t("menu.balance", lang), callback_data="menu:balance")
    b.button(text=i18n.t("menu.support", lang), callback_data="menu:support")
    b.button(text=i18n.t("menu.language", lang), callback_data="menu:lang")
    if is_admin:
        b.button(text=i18n.t("menu.admin", lang), callback_data="admin:menu")
    b.adjust(1, 2, 2, 2, 2, 1)
    return b.as_markup()


def back_kb(lang: str, cb: str = "menu:home") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("common.back", lang), callback_data=cb)
    return b.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("lang.ru"), callback_data="lang:ru")
    b.button(text=i18n.t("lang.kg"), callback_data="lang:kg")
    b.adjust(2)
    return b.as_markup()


def phone_request_kb(lang: str) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text=i18n.t("phone.btn_share", lang), request_contact=True))
    return b.as_markup(resize_keyboard=True, one_time_keyboard=True)


def confirm_kb(lang: str, yes_cb: str, no_cb: str = "menu:home") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("common.confirm", lang), callback_data=yes_cb)
    b.button(text=i18n.t("common.cancel", lang), callback_data=no_cb)
    b.adjust(2)
    return b.as_markup()


def home_kb(lang: str) -> InlineKeyboardMarkup:
    """Одна кнопка «В главное меню» — для пристёгивания к уведомлениям."""
    b = InlineKeyboardBuilder()
    b.button(text="🏠 В главное меню", callback_data="menu:home")
    return b.as_markup()
