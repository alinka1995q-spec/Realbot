import hashlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import User
from src.database.repositories import (
    AdminsRepo,
    BanksRepo,
    DepositsRepo,
    RequisitesRepo,
    TariffsRepo,
)
from src.i18n import i18n
from src.keyboards.common import back_kb, main_menu_kb
from src.keyboards.deposit import (
    bank_categories_kb,
    banks_in_category_kb,
    banks_kb,
    tariffs_kb,
)
from src.keyboards.admin import admin_deposit_actions_kb
from src.utils.format import (
    deposit_status_label,
    fmt_amount,
    fmt_date,
    deposit_start_display,
    fmt_date_human,
    tariff_payout_label,
    tariff_schedule_label,
)

logger = logging.getLogger(__name__)
router = Router(name="deposit")


class DepositFlow(StatesGroup):
    amount = State()
    fio = State()
    bank_category = State()
    bank = State()
    number = State()
    receipt = State()


def _cur(lang: str) -> str:
    return i18n.t("cur.default", lang)


# ---------- список тарифов ----------
@router.callback_query(F.data == "menu:tariffs")
async def show_tariffs(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    repo = TariffsRepo(session)
    tariffs = await repo.list_active()
    cur = _cur(db_user.lang)
    if not tariffs:
        await cb.message.edit_text(
            i18n.t("tariffs.empty", db_user.lang), reply_markup=back_kb(db_user.lang)
        )
        await cb.answer()
        return

    lines = [i18n.t("tariffs.title", db_user.lang), ""]
    for t in tariffs:
        desc = (t.description or "").strip()
        desc_block = f"\n<i>{desc}</i>\n" if desc else "\n"
        lines.append(
            i18n.t(
                "tariffs.item",
                db_user.lang,
                name=t.name,
                description=desc_block,
                min_amount=fmt_amount(t.min_amount),
                max_amount=fmt_amount(t.max_amount),
                cur=cur,
                duration=t.duration_days,
                schedule=tariff_schedule_label(t, db_user.lang),
                payout=tariff_payout_label(t),
            )
        )
    await cb.message.edit_text("\n".join(lines), reply_markup=back_kb(db_user.lang))
    await cb.answer()


# ---------- создание депозита ----------
@router.callback_query(F.data == "menu:new_deposit")
async def new_deposit(cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    repo = TariffsRepo(session)
    tariffs = await repo.list_active()
    if not tariffs:
        await cb.answer(i18n.t("tariffs.empty", db_user.lang), show_alert=True)
        return
    await state.clear()
    await cb.message.edit_text(
        i18n.t("deposit.choose_tariff", db_user.lang),
        reply_markup=tariffs_kb(tariffs, db_user.lang),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("dep:tariff:"))
async def choose_tariff(cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    tariff_id = int(cb.data.split(":")[2])
    repo = TariffsRepo(session)
    tariff = await repo.get(tariff_id)
    if not tariff or not tariff.is_active:
        await cb.answer("⚠️", show_alert=True)
        return

    # Проверяем лимит покупок этого тарифа на пользователя
    if tariff.max_purchases and tariff.max_purchases > 0:
        bought = await DepositsRepo(session).count_user_tariff(db_user.id, tariff.id)
        remaining = tariff.max_purchases - bought
        if remaining <= 0:
            await cb.message.edit_text(
                f"⛔ <b>Лимит покупок исчерпан</b>\n\n"
                f"Тариф <b>{tariff.name}</b> можно купить максимум "
                f"<b>{tariff.max_purchases}</b> раз(а).\n"
                f"У тебя уже оформлено: <b>{bought}</b>.",
                reply_markup=back_kb(db_user.lang),
            )
            await state.clear()
            await cb.answer()
            return

    await state.update_data(tariff_id=tariff.id)
    await state.set_state(DepositFlow.amount)
    cur = _cur(db_user.lang)
    await cb.message.edit_text(
        i18n.t(
            "deposit.enter_amount",
            db_user.lang,
            min=fmt_amount(tariff.min_amount),
            max=fmt_amount(tariff.max_amount),
            cur=cur,
        ),
        reply_markup=back_kb(db_user.lang),
    )
    await cb.answer()


@router.message(DepositFlow.amount, F.text)
async def step_amount(msg: Message, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    data = await state.get_data()
    tariff = await TariffsRepo(session).get(int(data["tariff_id"]))
    cur = _cur(db_user.lang)
    try:
        amount = Decimal(msg.text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        await msg.answer(
            i18n.t(
                "deposit.amount_invalid",
                db_user.lang,
                min=fmt_amount(tariff.min_amount),
                max=fmt_amount(tariff.max_amount),
                cur=cur,
            )
        )
        return
    if amount < Decimal(tariff.min_amount) or amount > Decimal(tariff.max_amount):
        await msg.answer(
            i18n.t(
                "deposit.amount_invalid",
                db_user.lang,
                min=fmt_amount(tariff.min_amount),
                max=fmt_amount(tariff.max_amount),
                cur=cur,
            )
        )
        return
    await state.update_data(amount=str(amount))
    await state.set_state(DepositFlow.fio)
    await msg.answer(i18n.t("deposit.enter_fio", db_user.lang))


@router.message(DepositFlow.fio, F.text)
async def step_fio(msg: Message, db_user: User, state: FSMContext, session: AsyncSession) -> None:
    fio = msg.text.strip()
    if len(fio) < 3:
        await msg.answer(i18n.t("deposit.enter_fio", db_user.lang))
        return
    await state.update_data(fio=fio)
    repo = BanksRepo(session)
    categories = await repo.list_active_categories()
    if not categories:
        # fallback: один список без категорий
        await state.set_state(DepositFlow.bank)
        await msg.answer(
            i18n.t("deposit.choose_bank", db_user.lang),
            reply_markup=banks_kb(["MBank", "O!Деньги", "Balance.kg", "USDT TRC20"], db_user.lang),
        )
        return
    if len(categories) == 1:
        # одна категория — пропускаем шаг
        cat = categories[0]
        banks = [b.name for b in await repo.list_active_in_category(cat)]
        await state.update_data(bank_category=cat)
        await state.set_state(DepositFlow.bank)
        await msg.answer(
            i18n.t("deposit.choose_bank", db_user.lang),
            reply_markup=banks_in_category_kb(banks, cat, db_user.lang),
        )
        return
    await state.set_state(DepositFlow.bank_category)
    await msg.answer(
        i18n.t("deposit.choose_bank", db_user.lang),
        reply_markup=bank_categories_kb(categories, db_user.lang, prefix="dep:cat"),
    )


@router.callback_query(DepositFlow.bank_category, F.data.startswith("dep:cat:"))
async def step_bank_category(
    cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    cat = cb.data.split(":", 2)[2]
    banks = [b.name for b in await BanksRepo(session).list_active_in_category(cat)]
    if not banks:
        await cb.answer("В этой категории нет банков", show_alert=True)
        return
    await state.update_data(bank_category=cat)
    await state.set_state(DepositFlow.bank)
    await cb.message.edit_text(
        f"<b>{cat}</b>\n\nВыбери способ:",
        reply_markup=banks_in_category_kb(banks, cat, db_user.lang),
    )
    await cb.answer()


@router.callback_query(F.data == "dep:back_cat")
async def step_back_to_categories(
    cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    categories = await BanksRepo(session).list_active_categories()
    await state.set_state(DepositFlow.bank_category)
    await cb.message.edit_text(
        i18n.t("deposit.choose_bank", db_user.lang),
        reply_markup=bank_categories_kb(categories, db_user.lang, prefix="dep:cat"),
    )
    await cb.answer()


@router.callback_query(DepositFlow.bank, F.data.startswith("dep:bank:"))
async def step_bank(cb: CallbackQuery, db_user: User, state: FSMContext) -> None:
    bank = cb.data.split(":", 2)[2]
    await state.update_data(bank=bank)
    await state.set_state(DepositFlow.number)
    await cb.message.edit_text(i18n.t("deposit.enter_number", db_user.lang))
    await cb.answer()


@router.message(DepositFlow.number, F.text)
async def step_number(
    msg: Message, db_user: User, state: FSMContext, session: AsyncSession
) -> None:
    number = msg.text.strip()
    if len(number) < 4:
        await msg.answer(i18n.t("deposit.enter_number", db_user.lang))
        return
    await state.update_data(number=number)

    requisite = await RequisitesRepo(session).pick_one_active()
    if requisite is None:
        await msg.answer(i18n.t("deposit.no_requisites", db_user.lang))
        await state.clear()
        return
    await state.update_data(requisite_id=requisite.id)

    data = await state.get_data()
    cur = _cur(db_user.lang)
    text = i18n.t(
        "deposit.show_requisite",
        db_user.lang,
        amount=fmt_amount(data["amount"]),
        cur=cur,
        bank=requisite.bank,
        number=requisite.number,
        holder=requisite.holder_name or "—",
    ) + "\n\n" + i18n.t("deposit.send_receipt", db_user.lang)
    await state.set_state(DepositFlow.receipt)
    await msg.answer(text)


@router.message(DepositFlow.receipt, F.photo | F.document)
async def step_receipt(
    msg: Message,
    db_user: User,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    data = await state.get_data()
    file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
    receipt_hash = hashlib.sha256(file_id.encode()).hexdigest()

    deposits = DepositsRepo(session)
    if await deposits.get_by_hash(receipt_hash):
        await msg.answer(i18n.t("deposit.duplicate_receipt", db_user.lang))
        return

    tariff_id = int(data["tariff_id"])
    # ещё раз проверяем лимит на момент создания
    tariff = await TariffsRepo(session).get(tariff_id)
    if tariff and tariff.max_purchases and tariff.max_purchases > 0:
        bought = await deposits.count_user_tariff(db_user.id, tariff_id)
        if bought >= tariff.max_purchases:
            await msg.answer(
                f"⛔ Лимит покупок этого тарифа исчерпан ({bought}/{tariff.max_purchases}).",
                reply_markup=main_menu_kb(db_user.lang),
            )
            await state.clear()
            return

    dep = await deposits.create_pending(
        user_id=db_user.id,
        tariff_id=tariff_id,
        amount=Decimal(data["amount"]),
        receipt_file_id=file_id,
        receipt_hash=receipt_hash,
        payout_full_name=data.get("fio"),
        payout_bank=data.get("bank"),
        payout_number=data.get("number"),
        requisite_id=data.get("requisite_id"),
    )
    await state.clear()

    await msg.answer(
        i18n.t("deposit.created", db_user.lang, id=dep.id),
        reply_markup=main_menu_kb(db_user.lang),
    )

    await _notify_admins_new_deposit(bot, session, dep.id)


async def _notify_admins_new_deposit(bot: Bot, session: AsyncSession, deposit_id: int) -> None:
    deposit = await DepositsRepo(session).get(deposit_id)
    if deposit is None:
        return
    admins = await AdminsRepo(session).list_all()
    cur = _cur("ru")
    user = await session.get(User, deposit.user_id)
    user_label = f"@{user.username}" if user and user.username else f"id:{user.telegram_id}"
    text = i18n.t(
        "admin.deposit.new",
        "ru",
        id=deposit.id,
        user=user_label,
        tariff=deposit.tariff.name if deposit.tariff else "?",
        amount=fmt_amount(deposit.amount),
        cur=cur,
        bank=deposit.payout_bank or "—",
        number=deposit.payout_number or "—",
        fio=deposit.payout_full_name or "—",
    )
    for a in admins:
        try:
            if deposit.receipt_file_id:
                await bot.send_photo(
                    a.telegram_id,
                    deposit.receipt_file_id,
                    caption=text,
                    reply_markup=admin_deposit_actions_kb(deposit.id, "ru"),
                )
            else:
                await bot.send_message(
                    a.telegram_id, text, reply_markup=admin_deposit_actions_kb(deposit.id, "ru")
                )
        except Exception as e:
            logger.warning("Failed notify admin %s: %s", a.telegram_id, e)


# ---------- список депозитов пользователя ----------
@router.callback_query(F.data == "menu:my_deposits")
async def my_deposits(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    from src.database.models import PayoutStatus

    deposits_repo = DepositsRepo(session)
    items = await deposits_repo.list_user(db_user.id)
    cur = _cur(db_user.lang)
    if not items:
        await cb.message.edit_text(
            i18n.t("deposit.list_empty", db_user.lang), reply_markup=back_kb(db_user.lang)
        )
        await cb.answer()
        return

    from src.database.repositories import PayoutsRepo

    payouts_repo = PayoutsRepo(session)
    cards: list[str] = ["📈 <b>Мои депозиты</b>"]
    for d in items:
        all_payouts = await payouts_repo.list_for_deposit(d.id)
        paid_count = sum(1 for p in all_payouts if p.status == PayoutStatus.PAID.value)
        total_count = len(all_payouts)
        left_count = sum(1 for p in all_payouts if p.status == PayoutStatus.PENDING.value)
        payout_amount = all_payouts[0].amount if all_payouts else (
            d.tariff.payout_fixed or 0 if d.tariff else 0
        )
        schedule = (
            tariff_schedule_label(d.tariff, db_user.lang) if d.tariff else "—"
        )
        cards.append(
            i18n.t(
                "deposit.card", db_user.lang,
                id=d.id,
                status=deposit_status_label(d.status, db_user.lang),
                tariff=(d.tariff.name if d.tariff else "?"),
                amount=fmt_amount(d.amount), cur=cur,
                payout=fmt_amount(payout_amount),
                schedule=schedule,
                start=fmt_date_human(deposit_start_display(d)) if d.started_at else fmt_date_human(d.created_at),
                end=fmt_date_human(d.ends_at) if d.ends_at else "—",
                paid_count=paid_count,
                total_count=total_count,
                left_count=left_count,
            )
        )
    text = "\n\n".join(cards)
    await cb.message.edit_text(text, reply_markup=back_kb(db_user.lang))
    await cb.answer()
