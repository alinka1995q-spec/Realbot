"""Админ-панель внутри бота.

Главное меню → разделы: депозиты, выплаты, выводы, тарифы, реквизиты,
пользователи, рефералы, рассылка, статистика, администраторы, тексты.
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import any_state
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AdminRole,
    DepositStatus,
    PayoutStatus,
    TariffPeriod,
    User,
    WithdrawalStatus,
)
from src.database.repositories import (
    AdminsRepo,
    BalanceRepo,
    BanksRepo,
    BroadcastsRepo,
    DepositsRepo,
    PayoutsRepo,
    ReferralsRepo,
    RequisitesRepo,
    SettingsRepo,
    TariffsRepo,
    TextsRepo,
    UsersRepo,
    WithdrawalsRepo,
)
from src.i18n import i18n
from src.keyboards.admin import (
    admin_deposit_actions_kb,
    admin_main_kb,
    admin_withdrawal_actions_kb,
    audience_kb,
)
from src.keyboards.common import back_kb
from src.services.broadcast_service import BroadcastService
from src.services.deposit_service import DepositService
from src.services.payout_service import PayoutService
from src.services.withdrawal_service import WithdrawalService
from src.utils.format import (
    deposit_start_display,
    deposit_status_label,
    fmt_amount,
    fmt_date,
    fmt_dt,
    payout_status_label,
    short_user,
)

logger = logging.getLogger(__name__)
router = Router(name="admin")


class AdminStates(StatesGroup):
    reject_reason = State()
    reject_wd_reason = State()
    add_admin = State()
    new_tariff = State()
    new_requisite = State()
    edit_text = State()
    user_search = State()
    user_balance = State()
    user_balance_comment = State()
    bc_content = State()
    bc_confirm = State()
    add_setting = State()
    edit_dep_amount = State()
    manual_payout = State()
    sub_channel = State()
    sub_group = State()
    sub_invite = State()
    sub_ch_id = State()
    sub_ch_url = State()
    sub_gr_id = State()
    sub_gr_url = State()
    sub_inv_id = State()
    sub_inv_url = State()
    new_bank = State()
    reject_reason_confirm = State()
    edit_dep_bank = State()
    edit_dep_number = State()
    edit_dep_fio = State()
    edit_dep_field_confirm = State()


# ---------- guard ----------
async def _ensure_admin(cb: CallbackQuery, is_admin: bool, lang: str) -> bool:
    if not is_admin:
        await cb.answer(i18n.t("admin.access_denied", lang), show_alert=True)
        return False
    return True


async def _ensure_full_admin(cb: CallbackQuery, is_full_admin: bool, lang: str) -> bool:
    """Полная роль admin (не moderator)."""
    if not is_full_admin:
        await cb.answer(i18n.t("admin.access_denied", lang), show_alert=True)
        return False
    return True


async def _safe_edit(cb: CallbackQuery, text: str, **kw) -> None:
    try:
        await cb.message.edit_text(text, **kw)
    except TelegramBadRequest:
        await cb.message.answer(text, **kw)


# ---------- меню ----------
@router.message(Command("admin"), StateFilter(any_state))
async def cmd_admin(msg: Message, state: FSMContext, is_admin: bool, db_user: User, is_full_admin: bool = False) -> None:
    if not is_admin:
        await msg.answer(i18n.t("admin.access_denied", db_user.lang))
        return
    await state.clear()
    await msg.answer(
        i18n.t("admin.menu.title", db_user.lang),
        reply_markup=admin_main_kb(db_user.lang, is_full_admin=is_full_admin),
    )


@router.callback_query(F.data == "admin:menu", StateFilter(any_state))
@router.callback_query(F.data == "adm:menu", StateFilter(any_state))
async def cb_admin_menu(
    cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext, is_full_admin: bool = False
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.clear()
    await _safe_edit(
        cb,
        i18n.t("admin.menu.title", db_user.lang),
        reply_markup=admin_main_kb(db_user.lang, is_full_admin=is_full_admin),
    )
    await cb.answer()


# ============================================================
#  ДЕПОЗИТЫ
# ============================================================
@router.callback_query(F.data == "adm:deposits")
async def adm_deposits(
    cb: CallbackQuery, is_admin: bool, is_full_admin: bool, db_user: User
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    b = InlineKeyboardBuilder()
    b.button(text="⏳ Ожидают", callback_data="adm:deposits:pending")
    if is_full_admin:
        b.button(text="🟢 Активные", callback_data="adm:deposits:active")
        b.button(text="✅ Завершённые", callback_data="adm:deposits:completed")
        b.button(text="❌ Отклонённые", callback_data="adm:deposits:rejected")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(2, 2, 1) if is_full_admin else b.adjust(1)
    await _safe_edit(cb, "📥 Депозиты:", reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:deposits:"))
async def adm_deposits_list(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool,
    is_full_admin: bool, db_user: User,
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    status = cb.data.split(":")[2]
    try:
        ds = DepositStatus(status)
    except ValueError:
        return
    # Модератор видит только ожидающие
    if not is_full_admin and ds != DepositStatus.PENDING:
        await cb.answer("⛔ Доступно только администратору", show_alert=True)
        return
    items = await DepositsRepo(session).list_by_status(ds, limit=20)
    if not items:
        await _safe_edit(cb, "Пусто.", reply_markup=back_kb(db_user.lang, "adm:deposits"))
        await cb.answer()
        return
    b = InlineKeyboardBuilder()
    lines = []
    for d in items:
        lines.append(
            f"#{d.id} | {fmt_amount(d.amount)} | {(d.tariff.name if d.tariff else '?')} | {fmt_date(d.created_at)}"
        )
        b.button(text=f"#{d.id}", callback_data=f"adm:dep:show:{d.id}")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:deposits")
    b.adjust(3)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:dep:show:"))
async def adm_deposit_show(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool,
    is_full_admin: bool, db_user: User,
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    d = await DepositsRepo(session).get(dep_id)
    if d is None:
        await cb.answer("Не найден", show_alert=True)
        return
    # модератору доступны только заявки в статусе "ожидают"
    if not is_full_admin and d.status != DepositStatus.PENDING.value:
        await cb.answer("⛔ Доступно только администратору", show_alert=True)
        return
    user = await UsersRepo(session).get_by_id(d.user_id)
    text = (
        f"Депозит #{d.id}\n"
        f"Статус: {deposit_status_label(d.status, db_user.lang)}\n"
        f"Пользователь: {short_user(user.telegram_id, user.username, user.full_name) if user else d.user_id}\n"
        f"Тариф: {d.tariff.name if d.tariff else '?'}\n"
        f"Сумма: {fmt_amount(d.amount)}\n"
        f"Создан: {fmt_dt(d.created_at)}\n"
        f"Старт: {fmt_dt(d.started_at)}\n"
        f"Окончание: {fmt_dt(d.ends_at)}\n"
        f"Выплата на: {d.payout_bank or '—'} {d.payout_number or '—'}\n"
        f"ФИО: {d.payout_full_name or '—'}"
    )
    b = InlineKeyboardBuilder()
    if d.status == DepositStatus.PENDING.value:
        b.button(text="✅ Подтвердить", callback_data=f"adm:dep:ok:{d.id}")
        b.button(text="❌ Отклонить", callback_data=f"adm:dep:no:{d.id}")
        b.button(text="✏️ Изменить данные", callback_data=f"adm:dep:edit:{d.id}")
        if is_full_admin:
            b.button(text="💰 Изменить сумму", callback_data=f"adm:dep:amt:{d.id}")
    if d.status == DepositStatus.ACTIVE.value and is_full_admin:
        b.button(text="💸 Ручная выплата", callback_data=f"adm:dep:pay:{d.id}")
        b.button(text="🚫 Закрыть", callback_data=f"adm:dep:close:{d.id}")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:deposits")
    b.adjust(2)
    await _safe_edit(cb, text, reply_markup=b.as_markup())
    await cb.answer()


# ----- изменение суммы депозита (только pending) -----
@router.callback_query(F.data.startswith("adm:dep:amt:"))
async def adm_dep_amt(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    await state.update_data(edit_dep_id=dep_id)
    await state.set_state(AdminStates.edit_dep_amount)
    await cb.message.answer(f"Введи новую сумму депозита #{dep_id}:")
    await cb.answer()


@router.message(AdminStates.edit_dep_amount, F.text)
async def adm_dep_amt_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    if not is_admin:
        return
    data = await state.get_data()
    dep_id = int(data["edit_dep_id"])
    try:
        amount = Decimal(msg.text.replace(" ", "").replace(",", "."))
    except Exception:
        await msg.answer("Неверный формат")
        return
    d = await DepositsRepo(session).get(dep_id)
    if d is None:
        await msg.answer("Не найден")
        await state.clear()
        return
    if d.status != DepositStatus.PENDING.value:
        await msg.answer("⚠️ Сумму можно менять только до подтверждения. Для активного депозита используй ручную выплату.")
        await state.clear()
        return
    await DepositsRepo(session).update_fields(dep_id, amount=amount)
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    await AdminsRepo(session).log(
        me.id if me else None,
        "deposit_amount_edit",
        target_type="deposit",
        target_id=dep_id,
        payload={"new_amount": str(amount)},
    )
    await state.clear()
    await msg.answer(f"✅ Сумма депозита #{dep_id} изменена на {amount}")


# ----- ручная выплата по активному депозиту -----
@router.callback_query(F.data.startswith("adm:dep:pay:"))
async def adm_dep_manual_payout(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    await state.update_data(manual_pay_dep_id=dep_id)
    await state.set_state(AdminStates.manual_payout)
    await cb.message.answer(f"Введи сумму ручной выплаты по депозиту #{dep_id}:")
    await cb.answer()


@router.message(AdminStates.manual_payout, F.text)
async def adm_dep_manual_payout_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not is_admin:
        return
    data = await state.get_data()
    dep_id = int(data["manual_pay_dep_id"])
    try:
        amount = Decimal(msg.text.replace(" ", "").replace(",", "."))
    except Exception:
        await msg.answer("Неверный формат")
        return
    d = await DepositsRepo(session).get(dep_id)
    if d is None:
        await msg.answer("Не найден")
        await state.clear()
        return
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    # создаём новую выплату со статусом pending и сразу её закрываем
    existing = await PayoutsRepo(session).list_for_deposit(dep_id)
    seq = (max((p.seq for p in existing), default=0)) + 1
    await PayoutsRepo(session).bulk_create([
        {
            "deposit_id": dep_id,
            "user_id": d.user_id,
            "amount": amount,
            "due_at": datetime.now(timezone.utc),
            "status": "pending",
            "seq": seq,
        }
    ])
    await session.flush()
    # последняя добавленная выплата
    refreshed = await PayoutsRepo(session).list_for_deposit(dep_id)
    new_payout = next((p for p in refreshed if p.seq == seq), None)
    if new_payout is not None:
        await PayoutService(session, bot).mark_paid(new_payout.id, me.id if me else None)
    await AdminsRepo(session).log(
        me.id if me else None,
        "manual_payout",
        target_type="deposit",
        target_id=dep_id,
        payload={"amount": str(amount)},
    )
    await state.clear()
    await msg.answer(f"✅ Ручная выплата {amount} по депозиту #{dep_id} проведена")


# Шаг 1: запросить подтверждение
@router.callback_query(F.data.startswith("adm:dep:ok:"))
async def adm_dep_confirm_ask(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User
) -> None:
    from src.keyboards.admin import confirm_action_kb

    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    d = await DepositsRepo(session).get(dep_id)
    if d is None:
        await cb.answer("Не найден", show_alert=True)
        return
    await cb.message.answer(
        f"❓ Вы уверены, что хотите <b>подтвердить</b> депозит #{dep_id}\n"
        f"на сумму <b>{fmt_amount(d.amount)} {i18n.t('cur.default', db_user.lang)}</b>?",
        reply_markup=confirm_action_kb(f"adm:dep:ok_yes:{dep_id}", f"adm:dep:show:{dep_id}"),
    )
    await cb.answer()


# Шаг 2: финальное действие
@router.callback_query(F.data.startswith("adm:dep:ok_yes:"))
async def adm_dep_confirm(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    admins_repo = AdminsRepo(session)
    me = await admins_repo.get_by_tg(db_user.telegram_id)
    svc = DepositService(session, bot)
    deposit = await svc.confirm(dep_id, me.id if me else None)
    if deposit is None:
        await cb.answer("Уже обработан или не найден", show_alert=True)
        return
    await admins_repo.log(
        me.id if me else None,
        "deposit_confirm",
        target_type="deposit",
        target_id=dep_id,
    )

    # уведомить пользователя
    user = await UsersRepo(session).get_by_id(deposit.user_id)
    payouts = await PayoutsRepo(session).list_for_deposit(deposit.id)
    cur = i18n.t("cur.default", user.lang) if user else "сом"
    if user:
        try:
            from src.keyboards.common import home_kb

            await bot.send_message(
                user.telegram_id,
                i18n.t(
                    "deposit.confirmed",
                    user.lang,
                    id=deposit.id,
                    amount=fmt_amount(deposit.amount),
                    cur=cur,
                    tariff=deposit.tariff.name if deposit.tariff else "?",
                    start=fmt_date(deposit_start_display(deposit)),
                    end=fmt_date(deposit.ends_at),
                    count=len(payouts),
                    payout=fmt_amount(payouts[0].amount) if payouts else "0",
                    first_payout=fmt_dt(payouts[0].due_at) if payouts else "—",
                ),
                reply_markup=home_kb(user.lang),
            )

            # Вторым сообщением — обязательная подписка на группу вкладчиков.
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
        except Exception as e:
            logger.warning("notify confirm: %s", e)
    await cb.answer("Подтверждено ✅")


@router.callback_query(F.data.startswith("adm:dep:no:"))
async def adm_dep_reject(
    cb: CallbackQuery, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    await state.update_data(reject_deposit_id=dep_id)
    await state.set_state(AdminStates.reject_reason)
    await cb.message.answer(i18n.t("admin.enter_reject_reason", db_user.lang))
    await cb.answer()


@router.message(AdminStates.reject_reason, F.text)
async def adm_dep_reject_reason_collect(
    msg: Message, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    """Шаг 1: записать причину, показать подтверждение."""
    from src.keyboards.admin import confirm_action_kb

    if not is_admin:
        return
    reason = (msg.text or "").strip()
    if not reason:
        await msg.answer("Причина не может быть пустой. Введи ещё раз.")
        return
    data = await state.get_data()
    dep_id = int(data["reject_deposit_id"])
    await state.update_data(reject_reason_text=reason)
    await state.set_state(AdminStates.reject_reason_confirm)
    await msg.answer(
        f"❓ Отклонить депозит #{dep_id}?\n\nПричина: <i>{reason}</i>",
        reply_markup=confirm_action_kb(f"adm:dep:no_yes:{dep_id}", f"adm:dep:show:{dep_id}"),
    )


@router.callback_query(F.data.startswith("adm:dep:no_yes:"), AdminStates.reject_reason_confirm)
async def adm_dep_reject_reason(
    cb: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    is_admin: bool,
    db_user: User,
    bot: Bot,
) -> None:
    """Шаг 2: реальное отклонение после подтверждения."""

    if not is_admin:
        return
    data = await state.get_data()
    dep_id = int(data["reject_deposit_id"])
    reason = data.get("reject_reason_text", "—")
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    svc = DepositService(session, bot)
    d = await svc.reject(dep_id, me.id if me else None, reason)
    await state.clear()
    if d is None:
        await cb.message.answer("Уже обработан или не найден")
        await cb.answer()
        return
    user = await UsersRepo(session).get_by_id(d.user_id)
    if user:
        try:
            from src.keyboards.common import home_kb

            await bot.send_message(
                user.telegram_id,
                i18n.t("deposit.rejected", user.lang, id=d.id, reason=reason),
                reply_markup=home_kb(user.lang),
            )
        except Exception:
            pass
    await cb.message.answer("Отклонено ❌")
    await cb.answer()


# ============================================================
#  РЕДАКТИРОВАНИЕ РЕКВИЗИТОВ ДЕПОЗИТА (доступно и модератору)
# ============================================================
@router.callback_query(F.data.startswith("adm:dep:edit:"))
async def adm_dep_edit_menu(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User
) -> None:
    from src.keyboards.admin import deposit_edit_kb

    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    d = await DepositsRepo(session).get(dep_id)
    if d is None:
        await cb.answer("Не найден", show_alert=True)
        return
    text = (
        f"✏️ <b>Изменение реквизитов депозита #{dep_id}</b>\n\n"
        f"🏦 Банк: <b>{d.payout_bank or '—'}</b>\n"
        f"💳 Номер: <code>{d.payout_number or '—'}</code>\n"
        f"👤 ФИО: <b>{d.payout_full_name or '—'}</b>\n\n"
        "Что меняем?"
    )
    await _safe_edit(cb, text, reply_markup=deposit_edit_kb(dep_id))
    await cb.answer()


async def _ask_dep_field(
    cb: CallbackQuery, state: FSMContext, st: State, dep_id: int, label: str
) -> None:
    await state.update_data(edit_dep_field_id=dep_id)
    await state.set_state(st)
    await cb.message.answer(f"Введи новое значение для поля <b>{label}</b>:")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:dep:setbank:"))
async def adm_dep_setbank(cb: CallbackQuery, state: FSMContext, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await _ask_dep_field(cb, state, AdminStates.edit_dep_bank, int(cb.data.split(":")[3]), "Банк")


@router.callback_query(F.data.startswith("adm:dep:setnum:"))
async def adm_dep_setnum(cb: CallbackQuery, state: FSMContext, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await _ask_dep_field(cb, state, AdminStates.edit_dep_number, int(cb.data.split(":")[3]), "Номер")


@router.callback_query(F.data.startswith("adm:dep:setfio:"))
async def adm_dep_setfio(cb: CallbackQuery, state: FSMContext, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await _ask_dep_field(cb, state, AdminStates.edit_dep_fio, int(cb.data.split(":")[3]), "ФИО")


async def _ask_dep_field_confirm(
    msg: Message, state: FSMContext, is_admin: bool, field: str, label: str,
) -> None:
    from src.keyboards.admin import confirm_action_kb

    if not is_admin:
        return
    data = await state.get_data()
    dep_id = int(data["edit_dep_field_id"])
    value = (msg.text or "").strip()
    if not value:
        await msg.answer("Значение не может быть пустым.")
        return
    await state.update_data(edit_dep_field_name=field, edit_dep_field_label=label, edit_dep_field_value=value)
    await state.set_state(AdminStates.edit_dep_field_confirm)
    await msg.answer(
        f"❓ Изменить поле <b>{label}</b> у депозита #{dep_id}?\n\n"
        f"Новое значение: <b>{value}</b>",
        reply_markup=confirm_action_kb(
            f"adm:dep:editfield:yes:{dep_id}",
            f"adm:dep:edit:{dep_id}",
        ),
    )


@router.message(AdminStates.edit_dep_bank, F.text)
async def adm_dep_bank_save(msg, state, is_admin, db_user):
    await _ask_dep_field_confirm(msg, state, is_admin, "payout_bank", "Банк")


@router.message(AdminStates.edit_dep_number, F.text)
async def adm_dep_number_save(msg, state, is_admin, db_user):
    await _ask_dep_field_confirm(msg, state, is_admin, "payout_number", "Номер")


@router.message(AdminStates.edit_dep_fio, F.text)
async def adm_dep_fio_save(msg, state, is_admin, db_user):
    await _ask_dep_field_confirm(msg, state, is_admin, "payout_full_name", "ФИО")


@router.callback_query(
    F.data.startswith("adm:dep:editfield:yes:"), AdminStates.edit_dep_field_confirm
)
async def adm_dep_editfield_apply(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession,
    is_admin: bool, db_user: User,
) -> None:
    from src.keyboards.admin import deposit_edit_kb

    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    data = await state.get_data()
    dep_id = int(cb.data.split(":")[4])
    field = data.get("edit_dep_field_name")
    label = data.get("edit_dep_field_label", "Поле")
    value = data.get("edit_dep_field_value")
    if not field or value is None:
        await cb.answer("Сессия истекла", show_alert=True)
        await state.clear()
        return
    await DepositsRepo(session).update_fields(dep_id, **{field: value})
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    await AdminsRepo(session).log(
        me.id if me else None,
        "deposit_requisite_edit",
        target_type="deposit", target_id=dep_id,
        payload={field: value},
    )
    await state.clear()
    d = await DepositsRepo(session).get(dep_id)
    text = (
        f"✅ <b>{label}</b> обновлён.\n\n"
        f"🏦 Банк: <b>{d.payout_bank or '—'}</b>\n"
        f"💳 Номер: <code>{d.payout_number or '—'}</code>\n"
        f"👤 ФИО: <b>{d.payout_full_name or '—'}</b>"
    )
    await _safe_edit(cb, text, reply_markup=deposit_edit_kb(dep_id))
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data.startswith("adm:dep:close:"))
async def adm_dep_close(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    dep_id = int(cb.data.split(":")[3])
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    svc = DepositService(session, bot)
    d = await svc.cancel(dep_id, me.id if me else None)
    if d is None:
        await cb.answer("Не найден", show_alert=True)
        return
    await cb.answer("Закрыт")


# ============================================================
#  ВЫПЛАТЫ
# ============================================================
@router.callback_query(F.data == "adm:payouts")
async def adm_payouts(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await PayoutsRepo(session).list_by_status(PayoutStatus.PENDING, limit=20)
    cur = i18n.t("cur.default", db_user.lang)
    if not items:
        await _safe_edit(cb, "Очередь выплат пуста.", reply_markup=back_kb(db_user.lang, "adm:menu"))
        await cb.answer()
        return
    lines = ["⏳ <b>Ожидающие выплаты</b>", ""]
    b = InlineKeyboardBuilder()
    for p in items:
        lines.append(f"#{p.id} | Депозит #{p.deposit_id} | {fmt_amount(p.amount)} {cur} | {fmt_dt(p.due_at)}")
        b.button(text=f"✅ #{p.id}", callback_data=f"adm:payout:ok:{p.id}")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(3)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:payout:ok:"))
async def adm_payout_ok(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    payout_id = int(cb.data.split(":")[3])
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    svc = PayoutService(session, bot)
    ok = await svc.mark_paid(payout_id, me.id if me else None)
    await cb.answer("✅ Выплачено" if ok else "Ошибка", show_alert=not ok)


# ============================================================
#  ВЫВОДЫ
# ============================================================
@router.callback_query(F.data == "adm:withdrawals")
async def adm_withdrawals(
    cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await WithdrawalsRepo(session).list_by_status(WithdrawalStatus.PENDING)
    if not items:
        await _safe_edit(cb, "Очередь выводов пуста.", reply_markup=back_kb(db_user.lang, "adm:menu"))
        await cb.answer()
        return
    b = InlineKeyboardBuilder()
    lines = ["🏧 <b>Заявки на вывод</b>", ""]
    for w in items:
        user = await UsersRepo(session).get_by_id(w.user_id)
        u = short_user(user.telegram_id, user.username, user.full_name) if user else f"#{w.user_id}"
        lines.append(f"#{w.id} | {u} | {fmt_amount(w.amount)} | {w.bank}/{w.number}")
        b.button(text=f"✅ #{w.id}", callback_data=f"adm:wd:ok:{w.id}")
        b.button(text=f"❌ #{w.id}", callback_data=f"adm:wd:no:{w.id}")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(2)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:wd:ok:"))
async def adm_wd_ok(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User, bot: Bot) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    wid = int(cb.data.split(":")[3])
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    ok = await WithdrawalService(session, bot).approve(wid, me.id if me else None)
    await cb.answer("✅" if ok else "Ошибка")


@router.callback_query(F.data.startswith("adm:wd:no:"))
async def adm_wd_no(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    wid = int(cb.data.split(":")[3])
    await state.update_data(reject_wd_id=wid)
    await state.set_state(AdminStates.reject_wd_reason)
    await cb.message.answer("Введи причину отклонения вывода:")
    await cb.answer()


@router.message(AdminStates.reject_wd_reason, F.text)
async def adm_wd_no_reason(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not is_admin:
        return
    data = await state.get_data()
    wid = int(data["reject_wd_id"])
    reason = msg.text.strip()
    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    await WithdrawalService(session, bot).reject(wid, me.id if me else None, reason)
    await state.clear()
    await msg.answer("Отклонено ❌")


# ============================================================
#  ТАРИФЫ
# ============================================================
@router.callback_query(F.data == "adm:tariffs")
async def adm_tariffs(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await TariffsRepo(session).list_all()
    lines = ["📋 <b>Тарифы</b>", ""]
    b = InlineKeyboardBuilder()
    for t in items:
        flag = "🟢" if t.is_active else "⚪️"
        lines.append(f"{flag} #{t.id} {t.name} | {fmt_amount(t.min_amount)}-{fmt_amount(t.max_amount)} | {t.duration_days}д")
        b.button(text=("⏸" if t.is_active else "▶️") + f" #{t.id}", callback_data=f"adm:tariff:toggle:{t.id}")
    b.button(text="➕ Добавить", callback_data="adm:tariff:new")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(2)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:tariff:toggle:"))
async def adm_tariff_toggle(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    tid = int(cb.data.split(":")[3])
    repo = TariffsRepo(session)
    t = await repo.get(tid)
    if t is None:
        await cb.answer("Не найден", show_alert=True)
        return
    await repo.set_active(tid, not t.is_active)
    await cb.answer("OK")
    # перерисуем
    await adm_tariffs(cb, session, is_admin, db_user)


@router.callback_query(F.data == "adm:tariff:new")
async def adm_tariff_new(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.new_tariff)
    await cb.message.answer(
        "Введи параметры тарифа в формате:\n"
        "<code>Название;мин;макс;дней;period;n;percent;fixed;body_included</code>\n\n"
        "Где:\n"
        "• period: daily / every_n_days / at_end\n"
        "• n: число дней между выплатами (для every_n_days)\n"
        "• percent ИЛИ fixed: одно из двух (другое = 0)\n"
        "• body_included: 1 или 0\n\n"
        "Пример: <code>Базовый;500;5000;10;daily;1;0;60;1</code>"
    )
    await cb.answer()


@router.message(AdminStates.new_tariff, F.text)
async def adm_tariff_new_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    if not is_admin:
        return
    try:
        parts = [p.strip() for p in msg.text.split(";")]
        name, mn, mx, days, period, n, percent, fixed, body = parts
        period_enum = TariffPeriod(period)
        repo = TariffsRepo(session)
        await repo.create(
            name=name,
            description=None,
            min_amount=Decimal(mn),
            max_amount=Decimal(mx),
            duration_days=int(days),
            period=period_enum,
            period_n_days=int(n),
            payout_percent=Decimal(percent) if Decimal(percent) > 0 else None,
            payout_fixed=Decimal(fixed) if Decimal(fixed) > 0 else None,
            body_included=body in {"1", "true", "yes"},
        )
        await state.clear()
        await msg.answer("✅ Тариф создан")
    except Exception as e:
        await msg.answer(f"Ошибка: {e}\n\nПопробуй ещё раз.")


# ============================================================
#  РЕКВИЗИТЫ
# ============================================================
@router.callback_query(F.data == "adm:requisites")
async def adm_requisites(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await RequisitesRepo(session).list_all()
    lines = ["🏦 <b>Реквизиты</b>", ""]
    b = InlineKeyboardBuilder()
    for r in items:
        flag = "🟢" if r.is_active else "⚪️"
        lines.append(f"{flag} #{r.id} {r.bank} | {r.number} | {r.holder_name or '—'}")
        b.button(text=("⏸" if r.is_active else "▶️") + f" #{r.id}", callback_data=f"adm:req:toggle:{r.id}")
    b.button(text="➕ Добавить", callback_data="adm:req:new")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(2)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:req:toggle:"))
async def adm_req_toggle(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    rid = int(cb.data.split(":")[3])
    r = await RequisitesRepo(session).get(rid)
    if r is None:
        await cb.answer("Не найден", show_alert=True)
        return
    await RequisitesRepo(session).set_active(rid, not r.is_active)
    await adm_requisites(cb, session, is_admin, db_user)
    await cb.answer("OK")


@router.callback_query(F.data == "adm:req:new")
async def adm_req_new(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.new_requisite)
    await cb.message.answer(
        "Введи реквизит в формате:\n"
        "<code>банк;номер;имя_получателя</code>\n\n"
        "Пример: <code>MBank;0700123456;Иванов Иван</code>"
    )
    await cb.answer()


@router.message(AdminStates.new_requisite, F.text)
async def adm_req_new_save(msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        return
    try:
        parts = [p.strip() for p in msg.text.split(";")]
        bank, number, holder = (parts + [None, None, None])[:3]
        await RequisitesRepo(session).create(bank=bank, number=number, holder_name=holder)
        await state.clear()
        await msg.answer("✅ Реквизит добавлен")
    except Exception as e:
        await msg.answer(f"Ошибка: {e}")


# ============================================================
#  ПОЛЬЗОВАТЕЛИ
# ============================================================
@router.callback_query(F.data == "adm:users")
async def adm_users(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.user_search)
    await cb.message.answer(
        "Введи Telegram ID, @username, ФИО, телефон или номер карты для поиска:"
    )
    await cb.answer()


@router.message(AdminStates.user_search, F.text)
async def adm_users_search(msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        return
    q = msg.text.strip().lstrip("@")
    users = await UsersRepo(session).search(q, limit=15)
    await state.clear()
    if not users:
        await msg.answer("🔍 Ничего не найдено.")
        return
    b = InlineKeyboardBuilder()
    lines = ["👥 <b>Результаты поиска</b>", ""]
    for u in users:
        lines.append(f"#{u.id} {short_user(u.telegram_id, u.username, u.full_name)} | {fmt_amount(u.balance)}")
        b.button(text=f"#{u.id}", callback_data=f"adm:user:{u.id}")
    b.button(text="↩️ Назад", callback_data="adm:menu")
    b.adjust(3)
    await msg.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm:user:"))
async def adm_user_card(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    uid = int(cb.data.split(":")[2])
    u = await UsersRepo(session).get_by_id(uid)
    if u is None:
        await cb.answer("Не найден", show_alert=True)
        return
    levels = await UsersRepo(session).count_referrals_by_level(uid)
    deps = await DepositsRepo(session).list_user(uid, limit=5)
    text = (
        f"<b>Пользователь #{u.id}</b>\n"
        f"TG: {u.telegram_id} | @{u.username or '—'}\n"
        f"ФИО: {u.full_name or '—'}\n"
        f"Телефон: {u.phone or '—'}\n"
        f"Язык: {u.lang}\n"
        f"Баланс: <b>{fmt_amount(u.balance)}</b>\n"
        f"Реферал-ID: {u.referrer_id or '—'}\n"
        f"Рефералы: L1={levels[1]} L2={levels[2]} L3={levels[3]}\n"
        f"Регистрация: {fmt_dt(u.created_at)}\n"
        f"Активность: {fmt_dt(u.last_active_at)}\n"
        f"Блок: {'🚫' if u.is_blocked else '✅'}"
    )
    if deps:
        text += "\n\nПоследние депозиты:\n" + "\n".join(
            f"#{d.id} {fmt_amount(d.amount)} | {deposit_status_label(d.status, 'ru')}"
            for d in deps
        )
    b = InlineKeyboardBuilder()
    b.button(text="💰 Изменить баланс", callback_data=f"adm:user:bal:{u.id}")
    b.button(text=("🔓 Разблок" if u.is_blocked else "🚫 Блок"), callback_data=f"adm:user:block:{u.id}")
    b.button(text="↩️ Назад", callback_data="adm:menu")
    b.adjust(1)
    await _safe_edit(cb, text, reply_markup=b.as_markup())
    await cb.answer()


def _balance_presets_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    presets = [100, 500, 1000, 5000]
    for v in presets:
        b.button(text=f"+{v}", callback_data=f"adm:bal:add:{v}")
    for v in presets:
        b.button(text=f"-{v}", callback_data=f"adm:bal:add:-{v}")
    b.button(text="✏️ Своя сумма", callback_data="adm:bal:custom")
    b.button(text="❌ Отмена", callback_data="adm:menu")
    b.adjust(4, 4, 1, 1)
    return b


@router.callback_query(F.data.startswith("adm:user:bal:"))
async def adm_user_bal(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    uid = int(cb.data.split(":")[3])
    await state.update_data(bal_user_id=uid)
    await cb.message.answer(
        f"Изменение баланса пользователя #{uid}\n\nВыбери сумму или введи свою:",
        reply_markup=_balance_presets_kb().as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:bal:add:"))
async def adm_bal_preset(
    cb: CallbackQuery, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    """Быстрое изменение по нажатию пресета."""
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    data = await state.get_data()
    uid = data.get("bal_user_id")
    if not uid:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    try:
        amount = Decimal(cb.data.split(":")[3])
    except Exception:
        await cb.answer("Ошибка", show_alert=True)
        return
    await state.update_data(bal_amount=str(amount))
    await state.set_state(AdminStates.user_balance_comment)
    await cb.message.answer(
        f"Сумма: <b>{amount}</b>\n\nКомментарий (необязательно):\n— или отправь «-» чтобы пропустить.",
    )
    await cb.answer()


@router.callback_query(F.data == "adm:bal:custom")
async def adm_bal_custom(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.user_balance)
    await cb.message.answer(
        "Введи сумму одним числом.\n"
        "• Положительное — начисление (например: <code>1500</code>)\n"
        "• Отрицательное — списание (например: <code>-200</code>)"
    )
    await cb.answer()


@router.message(AdminStates.user_balance, F.text)
async def adm_user_bal_amount(
    msg: Message, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    """Шаг 1 (только если выбрали «Своя сумма»): принимаем число."""
    if not is_admin:
        return
    raw = (msg.text or "").strip().replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except Exception:
        await msg.answer("❌ Нужно ввести число (например 500 или -200). Попробуй ещё раз.")
        return
    await state.update_data(bal_amount=str(amount))
    await state.set_state(AdminStates.user_balance_comment)
    await msg.answer(
        f"Сумма: <b>{amount}</b>\n\nКомментарий (необязательно):\n— или отправь «-» чтобы пропустить."
    )


@router.message(AdminStates.user_balance_comment, F.text)
async def adm_user_bal_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    """Шаг 2: комментарий + сохранение."""
    if not is_admin:
        return
    data = await state.get_data()
    uid = int(data["bal_user_id"])
    amount = Decimal(data["bal_amount"])
    comment_raw = (msg.text or "").strip()
    comment = None if comment_raw in {"", "-"} else comment_raw

    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    from src.database.models import BalanceChangeReason as BCR

    await UsersRepo(session).add_to_balance(uid, amount)
    await BalanceRepo(session).add(
        user_id=uid,
        amount=amount,
        reason=BCR.MANUAL_CREDIT if amount >= 0 else BCR.MANUAL_DEBIT,
        admin_id=me.id if me else None,
        comment=comment,
    )
    await AdminsRepo(session).log(
        me.id if me else None,
        "balance_adjust",
        target_type="user",
        target_id=uid,
        payload={"amount": str(amount), "comment": comment},
    )
    await state.clear()
    sign = "+" if amount >= 0 else ""
    await msg.answer(f"✅ Баланс пользователя #{uid} изменён: {sign}{amount}")


@router.callback_query(F.data.startswith("adm:user:block:"))
async def adm_user_block(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    uid = int(cb.data.split(":")[3])
    u = await UsersRepo(session).get_by_id(uid)
    if u is None:
        await cb.answer("Не найден", show_alert=True)
        return
    await UsersRepo(session).set_blocked(uid, not u.is_blocked)
    await cb.answer("OK")


# ============================================================
#  АДМИНИСТРАТОРЫ
# ============================================================
@router.callback_query(F.data == "adm:admins")
async def adm_admins(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await AdminsRepo(session).list_all()
    lines = ["<b>Администраторы</b>", ""]
    b = InlineKeyboardBuilder()
    for a in items:
        lines.append(f"<code>{a.telegram_id}</code>")
        if not a.is_root:
            b.button(text=f"Удалить {a.telegram_id}", callback_data=f"adm:admins:del:{a.id}")
    b.button(text="Добавить", callback_data="adm:admins:add")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(1)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data == "adm:admins:add")
async def adm_admins_add(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.add_admin)
    await cb.message.answer("Telegram ID нового админа:")
    await cb.answer()


@router.message(AdminStates.add_admin, F.text)
async def adm_admins_add_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    if not is_admin:
        return
    try:
        tg_id = int(msg.text.strip())
    except ValueError:
        await msg.answer("Нужно ввести число (Telegram ID).")
        return
    await AdminsRepo(session).add(tg_id, role=AdminRole.ADMIN)
    await state.clear()
    await msg.answer(f"✅ Добавлен админ {tg_id}")


@router.callback_query(F.data.startswith("adm:admins:del:"))
async def adm_admins_del(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    aid = int(cb.data.split(":")[3])
    ok = await AdminsRepo(session).remove(aid)
    await cb.answer("Удалён" if ok else "Нельзя удалить root", show_alert=not ok)
    if ok:
        await adm_admins(cb, session, is_admin, db_user)


# ============================================================
#  СТАТИСТИКА
# ============================================================
@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    users = UsersRepo(session)
    deposits = DepositsRepo(session)
    payouts = PayoutsRepo(session)
    refs = ReferralsRepo(session)
    now = datetime.now(timezone.utc)
    total_users = await users.count_total()
    new_d = await users.count_since(now - timedelta(days=1))
    new_w = await users.count_since(now - timedelta(days=7))
    new_m = await users.count_since(now - timedelta(days=30))
    active_dep = await deposits.count_by_status(DepositStatus.ACTIVE)
    sum_active = await deposits.sum_active()
    sum_payouts = await payouts.sum_paid()
    sum_refs = await refs.sum_total()
    total_deps = await deposits.count_by_status(DepositStatus.ACTIVE) + await deposits.count_by_status(DepositStatus.COMPLETED)
    top = await refs.top_referrers(limit=5)

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"➕ Новых за 24ч / 7д / 30д: {new_d} / {new_w} / {new_m}\n\n"
        f"💼 Активных депозитов: <b>{active_dep}</b>\n"
        f"💵 Сумма активных: <b>{fmt_amount(sum_active)}</b>\n"
        f"💸 Сумма выплат: <b>{fmt_amount(sum_payouts)}</b>\n"
        f"🎁 Сумма реф. начислений: <b>{fmt_amount(sum_refs)}</b>\n"
        f"📈 Всего депозитов: <b>{total_deps}</b>\n\n"
        f"<b>Топ рефоводов:</b>\n"
    )
    for tg, un, cnt, s in top:
        text += f"  • @{un or tg}: {fmt_amount(s)} ({cnt})\n"

    await _safe_edit(cb, text, reply_markup=back_kb(db_user.lang, "adm:menu"))
    await cb.answer()


# ============================================================
#  РЕФЕРАЛЫ
# ============================================================
@router.callback_query(F.data == "adm:referrals")
async def adm_referrals(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    top = await ReferralsRepo(session).top_referrers(limit=20)
    total = await ReferralsRepo(session).sum_total()
    lines = [f"🔗 <b>Реферальная программа</b>\n\nВсего начислено: <b>{fmt_amount(total)}</b>\n\n<b>Топ-20:</b>"]
    for tg, un, cnt, s in top:
        lines.append(f"@{un or tg}: {fmt_amount(s)} ({cnt} нач.)")
    await _safe_edit(cb, "\n".join(lines), reply_markup=back_kb(db_user.lang, "adm:menu"))
    await cb.answer()


# ============================================================
#  РАССЫЛКА
# ============================================================
@router.callback_query(F.data == "adm:broadcast")
async def adm_bc(cb: CallbackQuery, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await _safe_edit(
        cb,
        i18n.t("admin.broadcast.choose_audience", db_user.lang),
        reply_markup=audience_kb(db_user.lang),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:bc:aud:"))
async def adm_bc_aud(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    audience = cb.data.split(":")[3]
    await state.update_data(audience=audience)
    await state.set_state(AdminStates.bc_content)
    await cb.message.answer(i18n.t("admin.broadcast.send_content", db_user.lang))
    await cb.answer()


@router.message(AdminStates.bc_content)
async def adm_bc_content(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not is_admin:
        return
    data = await state.get_data()
    audience = data["audience"]

    text = msg.text or msg.caption
    media_type = None
    media_file_id = None
    if msg.photo:
        media_type = "photo"
        media_file_id = msg.photo[-1].file_id
    elif msg.video:
        media_type = "video"
        media_file_id = msg.video.file_id

    me = await AdminsRepo(session).get_by_tg(db_user.telegram_id)
    bc = await BroadcastsRepo(session).create(
        text=text,
        media_type=media_type,
        media_file_id=media_file_id,
        audience=audience,
        admin_id=me.id if me else None,
    )
    await session.flush()

    svc = BroadcastService(session, bot)
    ids = await svc.get_audience_ids(audience, None)
    await state.update_data(bc_id=bc.id)
    await state.set_state(AdminStates.bc_confirm)
    b = InlineKeyboardBuilder()
    b.button(text="🚀 Отправить", callback_data="adm:bc:send")
    b.button(text="❌ Отмена", callback_data="adm:menu")
    b.adjust(2)
    await msg.answer(
        i18n.t("admin.broadcast.confirm", db_user.lang, n=len(ids)),
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "adm:bc:send", AdminStates.bc_confirm)
async def adm_bc_send(
    cb: CallbackQuery, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User, bot: Bot
) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    data = await state.get_data()
    bc_id = int(data["bc_id"])
    await state.clear()
    svc = BroadcastService(session, bot)
    sent, failed = await svc.run(bc_id)
    await cb.message.answer(
        i18n.t("admin.broadcast.done", db_user.lang, sent=sent, failed=failed)
    )
    await cb.answer()


# ============================================================
#  ТЕКСТЫ
# ============================================================
@router.callback_query(F.data == "adm:texts")
async def adm_texts(cb: CallbackQuery, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await cb.message.answer(
        "📝 Тексты бота редактируются через веб-админку (раздел «Тексты»).\n\n"
        "Можно также вписать строку быстрого редактирования:\n"
        "<code>key;lang;значение</code>\n\n"
        "Пример: <code>menu.deposit;ru;💰 Новый депозит</code>"
    )

    from aiogram.fsm.context import FSMContext  # noqa
    await cb.answer()


@router.message(F.text.regexp(r"^[a-zA-Z0-9_\.]+;(ru|kg);"))
async def adm_text_quick_edit(msg: Message, session: AsyncSession, is_admin: bool) -> None:
    if not is_admin:
        return
    try:
        key, lang, value = msg.text.split(";", 2)
        await TextsRepo(session).set(key.strip(), lang.strip(), value.strip())
        # обновим in-memory кэш
        keys = await TextsRepo(session).keys()
        overrides: list[tuple[str, str, str]] = []
        for k in keys:
            for l in ("ru", "kg"):
                v = await TextsRepo(session).get(k, l)
                if v is not None:
                    overrides.append((k, l, v))
        i18n.reload_overrides(overrides)
        await msg.answer("✅ Текст обновлён")
    except Exception as e:
        await msg.answer(f"Ошибка: {e}")


# ============================================================
#  ПОДПИСКИ (обязательный канал, группа, инвайт инвесторов)
# ============================================================
def _subs_menu_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="📣 Канал", callback_data="adm:subs:edit:channel")
    b.button(text="💬 Группа", callback_data="adm:subs:edit:group")
    b.button(text="🔐 Инвайт в группу вкладчиков", callback_data="adm:subs:edit:invite")
    b.button(text="🗑 Очистить канал", callback_data="adm:subs:clear:channel")
    b.button(text="🗑 Очистить группу", callback_data="adm:subs:clear:group")
    b.button(text="🗑 Очистить инвайт", callback_data="adm:subs:clear:invite")
    b.button(text="↩️ Назад", callback_data="adm:menu")
    b.adjust(1, 1, 1, 2, 1, 1)
    return b


async def _render_subs_menu(cb: CallbackQuery, session: AsyncSession) -> None:
    repo = SettingsRepo(session)
    ch_id = await repo.get("required_channel_id", "") or "—"
    ch_url = await repo.get("required_channel_url", "") or "—"
    gr_id = await repo.get("required_group_id", "") or "—"
    gr_url = await repo.get("required_group_url", "") or "—"
    inv_id = await repo.get("investors_group_id", "") or "—"
    inv_url = await repo.get("investors_group_url", "") or (await repo.get("investors_group_invite", "") or "—")
    text = (
        "<b>📢 Обязательные подписки</b>\n\n"
        f"📣 <b>Канал</b>\n"
        f"   ID для проверки: <code>{ch_id}</code>\n"
        f"   Ссылка для юзеров: <code>{ch_url}</code>\n\n"
        f"💬 <b>Группа</b>\n"
        f"   ID для проверки: <code>{gr_id}</code>\n"
        f"   Ссылка для юзеров: <code>{gr_url}</code>\n\n"
        f"🔐 <b>Группа вкладчиков</b> (только для юзеров с подтв. депозитом)\n"
        f"   ID для проверки: <code>{inv_id}</code>\n"
        f"   Ссылка для юзеров: <code>{inv_url}</code>\n\n"
        "Бот должен быть админом в канале/группе, иначе проверка не работает."
    )
    await _safe_edit(cb, text, reply_markup=_subs_menu_kb().as_markup())


@router.callback_query(F.data == "adm:subs")
async def adm_subs(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await _render_subs_menu(cb, session)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subs:edit:"))
async def adm_subs_edit(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    kind = cb.data.split(":")[3]
    if kind == "channel":
        await state.set_state(AdminStates.sub_ch_id)
        await cb.message.answer(
            "📣 <b>Добавление канала</b>\n\n"
            "Шаг 1 из 2 — нужен ID канала.\n\n"
            "• <b>Перешли</b> сюда любое сообщение из канала, ИЛИ\n"
            "• пришли <code>chat_id</code> (например <code>-1001234567890</code>), ИЛИ\n"
            "• пришли <code>@username</code> публичного канала.\n\n"
            "⚠️ Бот должен быть админом в этом канале."
        )
    elif kind == "group":
        await state.set_state(AdminStates.sub_gr_id)
        await cb.message.answer(
            "💬 <b>Добавление группы</b>\n\n"
            "Шаг 1 из 2 — нужен ID группы.\n\n"
            "• <b>Перешли</b> сюда любое сообщение из группы, ИЛИ\n"
            "• пришли <code>chat_id</code> (например <code>-1001234567890</code>), ИЛИ\n"
            "• пришли <code>@username</code> публичной группы.\n\n"
            "⚠️ Бот должен быть админом в этой группе."
        )
    elif kind == "invite":
        await state.set_state(AdminStates.sub_inv_id)
        await cb.message.answer(
            "🔐 <b>Добавление группы вкладчиков</b>\n\n"
            "Шаг 1 из 2 — нужен ID группы.\n\n"
            "• <b>Перешли</b> сюда любое сообщение из группы, ИЛИ\n"
            "• пришли <code>chat_id</code> (например <code>-1001234567890</code>), ИЛИ\n"
            "• пришли <code>@username</code> публичной группы.\n\n"
            "⚠️ Бот должен быть админом в этой группе.\n"
            "Эта подписка обязательна только для юзеров с подтверждённым депозитом."
        )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subs:clear:"))
async def adm_subs_clear(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    kind = cb.data.split(":")[3]
    clear_map = {
        "channel": ["required_channel_id", "required_channel_url", "required_channel"],
        "group": ["required_group_id", "required_group_url", "required_group"],
        "invite": ["investors_group_id", "investors_group_url", "investors_group_invite"],
    }
    for k in clear_map.get(kind, []):
        await SettingsRepo(session).set(k, "")
    await _render_subs_menu(cb, session)
    await cb.answer("Очищено")


async def _resolve_chat_input(bot: Bot, msg: Message) -> tuple[int | None, str | None]:
    """Возвращает (chat_id, error). Пытается извлечь chat_id из:
    - пересланного сообщения (forward_from_chat)
    - текстового chat_id вида -100...
    - @username (через get_chat)
    """
    # 1) форвард
    if msg.forward_from_chat is not None:
        return msg.forward_from_chat.id, None
    text = (msg.text or "").strip()
    if not text:
        return None, "Пришли пересланное сообщение или chat_id."
    # 2) числовой id
    try:
        return int(text), None
    except ValueError:
        pass
    # 3) @username — резолвим
    handle = text if text.startswith("@") else f"@{text}"
    try:
        chat = await bot.get_chat(handle)
        return chat.id, None
    except Exception as e:
        return None, f"Не удалось получить chat по {handle}: {e}"


async def _verify_bot_in_chat(bot: Bot, chat_id: int) -> tuple[bool, str]:
    """Проверяет, что бот реально находится в чате и может проверять подписки."""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status in {"administrator", "creator", "member"}:
            return True, ""
        return False, f"Бот в чате как «{member.status}», нужен «administrator»."
    except Exception as e:
        return False, f"Не получилось проверить: {e}"


@router.message(AdminStates.sub_ch_id)
async def adm_subs_ch_id(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, bot: Bot
) -> None:
    if not is_admin:
        return
    chat_id, err = await _resolve_chat_input(bot, msg)
    if chat_id is None:
        await msg.answer(f"⚠️ {err}\n\nПопробуй ещё раз.")
        return
    ok, vmsg = await _verify_bot_in_chat(bot, chat_id)
    if not ok:
        await msg.answer(
            f"⚠️ {vmsg}\n\n"
            f"chat_id <code>{chat_id}</code> не подходит.\n"
            "Добавь бота админом в канал и попробуй снова."
        )
        return
    await state.update_data(ch_id=str(chat_id))
    await state.set_state(AdminStates.sub_ch_url)
    await msg.answer(
        f"✅ ID канала сохранён: <code>{chat_id}</code>\n\n"
        "Шаг 2 из 2 — пришли <b>ссылку</b>, которую увидит юзер на кнопке «Подписаться» "
        "(<code>https://t.me/username</code> или инвайт-ссылка <code>https://t.me/+...</code>):"
    )


@router.message(AdminStates.sub_ch_url, F.text)
async def adm_subs_ch_url(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    if not is_admin:
        return
    url = (msg.text or "").strip()
    if not url.startswith("http") and not url.startswith("@"):
        await msg.answer("⚠️ Нужна полноценная ссылка https://t.me/... или @username")
        return
    data = await state.get_data()
    chat_id = data.get("ch_id", "")
    repo = SettingsRepo(session)
    await repo.set("required_channel_id", chat_id)
    await repo.set("required_channel_url", url)
    await state.clear()
    await msg.answer(
        f"✅ Канал настроен.\n\n"
        f"ID: <code>{chat_id}</code>\n"
        f"Ссылка для юзеров: <code>{url}</code>"
    )


@router.message(AdminStates.sub_gr_id)
async def adm_subs_gr_id(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, bot: Bot
) -> None:
    if not is_admin:
        return
    chat_id, err = await _resolve_chat_input(bot, msg)
    if chat_id is None:
        await msg.answer(f"⚠️ {err}\n\nПопробуй ещё раз.")
        return
    ok, vmsg = await _verify_bot_in_chat(bot, chat_id)
    if not ok:
        await msg.answer(
            f"⚠️ {vmsg}\n\n"
            f"chat_id <code>{chat_id}</code> не подходит.\n"
            "Добавь бота админом в группу и попробуй снова."
        )
        return
    await state.update_data(gr_id=str(chat_id))
    await state.set_state(AdminStates.sub_gr_url)
    await msg.answer(
        f"✅ ID группы сохранён: <code>{chat_id}</code>\n\n"
        "Шаг 2 из 2 — пришли <b>ссылку</b>, которую увидит юзер на кнопке «Вступить» "
        "(инвайт-ссылка <code>https://t.me/+...</code> или <code>@username</code>):"
    )


@router.message(AdminStates.sub_gr_url, F.text)
async def adm_subs_gr_url(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    if not is_admin:
        return
    url = (msg.text or "").strip()
    if not url.startswith("http") and not url.startswith("@"):
        await msg.answer("⚠️ Нужна полноценная ссылка https://t.me/... или @username")
        return
    data = await state.get_data()
    chat_id = data.get("gr_id", "")
    repo = SettingsRepo(session)
    await repo.set("required_group_id", chat_id)
    await repo.set("required_group_url", url)
    await state.clear()
    await msg.answer(
        f"✅ Группа настроена.\n\n"
        f"ID: <code>{chat_id}</code>\n"
        f"Ссылка для юзеров: <code>{url}</code>"
    )


@router.message(AdminStates.sub_invite, F.text)
async def adm_subs_save_invite(msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        return
    val = (msg.text or "").strip()
    await SettingsRepo(session).set("investors_group_invite", val)
    await state.clear()
    await msg.answer(f"✅ Инвайт сохранён: <code>{val or '—'}</code>")


@router.message(AdminStates.sub_inv_id)
async def adm_subs_inv_id(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, bot: Bot
) -> None:
    if not is_admin:
        return
    chat_id, err = await _resolve_chat_input(bot, msg)
    if chat_id is None:
        await msg.answer(f"⚠️ {err}\n\nПопробуй ещё раз.")
        return
    ok, vmsg = await _verify_bot_in_chat(bot, chat_id)
    if not ok:
        await msg.answer(
            f"⚠️ {vmsg}\n\n"
            f"chat_id <code>{chat_id}</code> не подходит.\n"
            "Добавь бота админом в группу и попробуй снова."
        )
        return
    await state.update_data(inv_id=str(chat_id))
    await state.set_state(AdminStates.sub_inv_url)
    await msg.answer(
        f"✅ ID группы вкладчиков сохранён: <code>{chat_id}</code>\n\n"
        "Шаг 2 из 2 — пришли <b>ссылку</b>, которую увидит юзер на кнопке «Вступить» "
        "(инвайт-ссылка <code>https://t.me/+...</code> или <code>@username</code>):"
    )


@router.message(AdminStates.sub_inv_url, F.text)
async def adm_subs_inv_url(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    if not is_admin:
        return
    url = (msg.text or "").strip()
    if not url.startswith("http") and not url.startswith("@"):
        await msg.answer("⚠️ Нужна полноценная ссылка https://t.me/... или @username")
        return
    data = await state.get_data()
    chat_id = data.get("inv_id", "")
    repo = SettingsRepo(session)
    await repo.set("investors_group_id", chat_id)
    await repo.set("investors_group_url", url)
    # для обратной совместимости — старый ключ тоже обновляем
    await repo.set("investors_group_invite", url)
    await state.clear()
    await msg.answer(
        f"✅ Группа вкладчиков настроена.\n\n"
        f"ID: <code>{chat_id}</code>\n"
        f"Ссылка для юзеров: <code>{url}</code>"
    )


# ============================================================
#  БАНКИ (справочник для выбора при депозите и выводе)
# ============================================================
@router.callback_query(F.data == "adm:banks")
async def adm_banks(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    items = await BanksRepo(session).list_all()
    lines = ["🏦 <b>Банки и платёжные системы</b>", ""]
    b = InlineKeyboardBuilder()
    if items:
        for x in items:
            flag = "🟢" if x.is_active else "⚪️"
            lines.append(f"{flag} #{x.id} {x.name}")
            label = "⏸" if x.is_active else "▶️"
            b.button(text=f"{label} {x.name[:20]}", callback_data=f"adm:bank:toggle:{x.id}")
            b.button(text=f"🗑 {x.name[:20]}", callback_data=f"adm:bank:del:{x.id}")
    else:
        lines.append("<i>Список пуст — добавьте первый банк.</i>")
    b.button(text="➕ Добавить банк", callback_data="adm:bank:new")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="adm:menu")
    b.adjust(2)
    await _safe_edit(cb, "\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:bank:toggle:"))
async def adm_bank_toggle(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    bid = int(cb.data.split(":")[3])
    b = await BanksRepo(session).get(bid)
    if b:
        await BanksRepo(session).set_active(bid, not b.is_active)
    await adm_banks(cb, session, is_admin, db_user)


@router.callback_query(F.data.startswith("adm:bank:del:"))
async def adm_bank_del(cb: CallbackQuery, session: AsyncSession, is_admin: bool, db_user: User) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    bid = int(cb.data.split(":")[3])
    await BanksRepo(session).delete(bid)
    await adm_banks(cb, session, is_admin, db_user)
    await cb.answer("Удалён")


@router.callback_query(F.data == "adm:bank:new")
async def adm_bank_new(cb: CallbackQuery, is_admin: bool, db_user: User, state: FSMContext) -> None:
    if not await _ensure_admin(cb, is_admin, db_user.lang):
        return
    await state.set_state(AdminStates.new_bank)
    await cb.message.answer(
        "Введи новый банк в формате:\n\n"
        "<code>Категория | Название</code>\n\n"
        "Примеры:\n"
        "• <code>Банки | Optima Bank</code>\n"
        "• <code>Крипта | USDT TRC20</code>\n"
        "• <code>КриптоБот | BTC</code>\n\n"
        "Если категорию не указать — будет «Банки»."
    )
    await cb.answer()


@router.message(AdminStates.new_bank, F.text)
async def adm_bank_new_save(
    msg: Message, session: AsyncSession, state: FSMContext, is_admin: bool, db_user: User
) -> None:
    if not is_admin:
        return
    raw = (msg.text or "").strip()
    if not raw:
        await msg.answer("Название не может быть пустым.")
        return
    # Формат: «Категория | Название» либо просто «Название» (тогда категория = Банки)
    if "|" in raw:
        category, _, name = raw.partition("|")
        category = category.strip() or "Банки"
        name = name.strip()
    else:
        category = "Банки"
        name = raw
    if not name:
        await msg.answer("Название не может быть пустым.")
        return
    await BanksRepo(session).create(name=name, category=category)
    await state.clear()
    await msg.answer(f"✅ Добавлен: <b>{name}</b>\n📂 Категория: <i>{category}</i>")
