from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User
from src.database.repositories import (
    AdminsRepo,
    BanksRepo,
    SettingsRepo,
    UsersRepo,
)
from src.i18n import i18n
from src.keyboards.common import back_kb, main_menu_kb
from src.keyboards.deposit import bank_categories_kb, banks_in_category_kb, banks_kb
from src.services.withdrawal_service import WithdrawalService
from src.utils.format import fmt_amount

router = Router(name="balance")


class WithdrawFlow(StatesGroup):
    amount = State()
    bank_category = State()
    bank = State()
    number = State()
    fio = State()


@router.callback_query(F.data == "menu:balance")
async def show_balance(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    user = await UsersRepo(session).get_by_id(db_user.id)
    cur = i18n.t("cur.default", db_user.lang)
    text = i18n.t("balance.title", db_user.lang, balance=fmt_amount(user.balance), cur=cur)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text=i18n.t("balance.btn_withdraw", db_user.lang), callback_data="balance:withdraw")
    b.button(text=i18n.t("common.back", db_user.lang), callback_data="menu:home")
    b.adjust(1)
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data == "balance:withdraw")
async def start_withdraw(
    cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    settings_repo = SettingsRepo(session)
    min_w = await settings_repo.get_decimal("min_withdrawal", Decimal("100"))
    user = await UsersRepo(session).get_by_id(db_user.id)
    cur = i18n.t("cur.default", db_user.lang)

    await state.set_state(WithdrawFlow.amount)
    await cb.message.edit_text(
        i18n.t(
            "withdrawal.enter_amount",
            db_user.lang,
            min=fmt_amount(min_w),
            balance=fmt_amount(user.balance),
            cur=cur,
        ),
        reply_markup=back_kb(db_user.lang),
    )
    await cb.answer()


@router.message(WithdrawFlow.amount, F.text)
async def w_amount(msg: Message, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    cur = i18n.t("cur.default", db_user.lang)
    try:
        amount = Decimal(msg.text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        await msg.answer(i18n.t("withdrawal.amount_invalid", db_user.lang))
        return
    user = await UsersRepo(session).get_by_id(db_user.id)
    if amount <= 0:
        await msg.answer(i18n.t("withdrawal.amount_invalid", db_user.lang))
        return
    if Decimal(user.balance) < amount:
        await msg.answer(
            i18n.t("withdrawal.no_funds", db_user.lang, balance=fmt_amount(user.balance), cur=cur)
        )
        return
    await state.update_data(amount=str(amount))
    repo = BanksRepo(session)
    categories = await repo.list_active_categories()
    if not categories:
        await state.set_state(WithdrawFlow.bank)
        await msg.answer(
            i18n.t("withdrawal.choose_bank", db_user.lang),
            reply_markup=banks_kb(["MBank", "O!Деньги", "Balance.kg", "USDT TRC20"], db_user.lang, prefix="wd:bank"),
        )
        return
    if len(categories) == 1:
        cat = categories[0]
        banks = [b.name for b in await repo.list_active_in_category(cat)]
        await state.update_data(bank_category=cat)
        await state.set_state(WithdrawFlow.bank)
        await msg.answer(
            i18n.t("withdrawal.choose_bank", db_user.lang),
            reply_markup=banks_in_category_kb(banks, cat, db_user.lang, prefix="wd:bank", back_cb="wd:back_cat"),
        )
        return
    await state.set_state(WithdrawFlow.bank_category)
    await msg.answer(
        i18n.t("withdrawal.choose_bank", db_user.lang),
        reply_markup=bank_categories_kb(categories, db_user.lang, prefix="wd:cat"),
    )


@router.callback_query(WithdrawFlow.bank_category, F.data.startswith("wd:cat:"))
async def w_bank_category(
    cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    cat = cb.data.split(":", 2)[2]
    banks = [b.name for b in await BanksRepo(session).list_active_in_category(cat)]
    if not banks:
        await cb.answer("В этой категории нет банков", show_alert=True)
        return
    await state.update_data(bank_category=cat)
    await state.set_state(WithdrawFlow.bank)
    await cb.message.edit_text(
        f"<b>{cat}</b>\n\nВыбери способ:",
        reply_markup=banks_in_category_kb(banks, cat, db_user.lang, prefix="wd:bank", back_cb="wd:back_cat"),
    )
    await cb.answer()


@router.callback_query(F.data == "wd:back_cat")
async def w_back_to_categories(
    cb: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    categories = await BanksRepo(session).list_active_categories()
    await state.set_state(WithdrawFlow.bank_category)
    await cb.message.edit_text(
        i18n.t("withdrawal.choose_bank", db_user.lang),
        reply_markup=bank_categories_kb(categories, db_user.lang, prefix="wd:cat"),
    )
    await cb.answer()


@router.callback_query(WithdrawFlow.bank, F.data.startswith("wd:bank:"))
async def w_bank(cb: CallbackQuery, db_user: User, state: FSMContext) -> None:
    bank = cb.data.split(":", 2)[2]
    await state.update_data(bank=bank)
    await state.set_state(WithdrawFlow.number)
    await cb.message.edit_text(i18n.t("withdrawal.enter_number", db_user.lang))
    await cb.answer()


@router.message(WithdrawFlow.number, F.text)
async def w_number(msg: Message, db_user: User, state: FSMContext) -> None:
    number = msg.text.strip()
    if len(number) < 4:
        await msg.answer(i18n.t("withdrawal.enter_number", db_user.lang))
        return
    await state.update_data(number=number)
    await state.set_state(WithdrawFlow.fio)
    await msg.answer(i18n.t("withdrawal.enter_fio", db_user.lang))


@router.message(WithdrawFlow.fio, F.text)
async def w_fio(
    msg: Message,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    fio = msg.text.strip()
    if len(fio) < 3:
        await msg.answer(i18n.t("withdrawal.enter_fio", db_user.lang))
        return
    data = await state.get_data()
    await state.clear()

    svc = WithdrawalService(session, bot)
    ok, wid, err = await svc.request(
        user_id=db_user.id,
        amount=Decimal(data["amount"]),
        bank=data["bank"],
        number=data["number"],
        holder_name=fio,
    )
    if not ok:
        cur = i18n.t("cur.default", db_user.lang)
        if err == "need_active":
            await msg.answer(i18n.t("referrals.need_active", db_user.lang))
        elif err == "no_funds":
            user = await UsersRepo(session).get_by_id(db_user.id)
            await msg.answer(
                i18n.t("withdrawal.no_funds", db_user.lang, balance=fmt_amount(user.balance), cur=cur)
            )
        else:
            await msg.answer(i18n.t("common.error_generic", db_user.lang))
        return

    await msg.answer(
        i18n.t("withdrawal.created", db_user.lang, id=wid),
        reply_markup=main_menu_kb(db_user.lang),
    )

    # уведомить администраторов
    from src.keyboards.admin import admin_withdrawal_actions_kb

    admins = await AdminsRepo(session).list_all()
    text = (
        f"🔔 Новая заявка на вывод #{wid}\n\n"
        f"👤 @{db_user.username or db_user.telegram_id}\n"
        f"💵 Сумма: {fmt_amount(data['amount'])}\n"
        f"🏦 {data['bank']} - <code>{data['number']}</code>\n"
        f"👤 {fio}"
    )
    for a in admins:
        try:
            await bot.send_message(
                a.telegram_id, text, reply_markup=admin_withdrawal_actions_kb(wid, "ru")
            )
        except Exception:
            pass
