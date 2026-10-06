from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.models import Requisite, Tariff
from src.i18n import i18n


def tariffs_kb(tariffs: list[Tariff], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in tariffs:
        b.button(text=t.name, callback_data=f"dep:tariff:{t.id}")
    b.button(text=i18n.t("common.back", lang), callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def quantity_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="×1", callback_data="dep:qty:1")
    b.button(text="×5", callback_data="dep:qty:5")
    b.button(text="✍️ Своё количество", callback_data="dep:qty:custom")
    b.button(text=i18n.t("common.cancel", lang), callback_data="menu:home")
    b.adjust(2, 1, 1)
    return b.as_markup()


def banks_kb(banks: list[str], lang: str, prefix: str = "dep:bank") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for bank in banks:
        b.button(text=bank, callback_data=f"{prefix}:{bank}")
    b.button(text=i18n.t("common.cancel", lang), callback_data="menu:home")
    b.adjust(2)
    return b.as_markup()


def bank_categories_kb(categories: list[str], lang: str, prefix: str = "dep:cat") -> InlineKeyboardMarkup:
    """Список категорий банков (Банки / Крипта / КриптоБот / ...)."""
    b = InlineKeyboardBuilder()
    for c in categories:
        b.button(text=c, callback_data=f"{prefix}:{c}")
    b.button(text=i18n.t("common.cancel", lang), callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def banks_in_category_kb(
    banks: list[str], category: str, lang: str, prefix: str = "dep:bank", back_cb: str = "dep:back_cat"
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for bank in banks:
        b.button(text=bank, callback_data=f"{prefix}:{bank}")
    b.button(text="← К категориям", callback_data=back_cb)
    b.button(text=i18n.t("common.cancel", lang), callback_data="menu:home")
    b.adjust(2, 1, 1)
    return b.as_markup()


def requisites_kb(requisites: list[Requisite], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in requisites:
        b.button(text=f"{r.bank}", callback_data=f"dep:req:{r.id}")
    b.button(text=i18n.t("common.cancel", lang), callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()
