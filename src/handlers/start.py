import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import User
from src.database.repositories import UsersRepo
from src.i18n import i18n
from src.keyboards.common import lang_kb, main_menu_kb
from src.services.notifications import notify_admins

logger = logging.getLogger(__name__)
router = Router(name="start")


def _parse_ref(args: str | None) -> int | None:
    if not args:
        return None
    try:
        return int(args.strip())
    except (ValueError, AttributeError):
        return None


@router.message(CommandStart(deep_link=True), StateFilter(any_state))
@router.message(CommandStart(), StateFilter(any_state))
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    is_admin: bool,
    bot: Bot,
    is_new_user: bool = False,
) -> None:
    await state.clear()
    args = message.text.removeprefix("/start").strip()
    ref_id = _parse_ref(args)
    is_new = is_new_user

    if ref_id and db_user.referrer_id is None and ref_id != db_user.id:
        users = UsersRepo(session)
        ref = await users.get_by_id(ref_id)
        if ref is not None:
            db_user.referrer_id = ref.id
            # глубина = уровень реферера + 1
            db_user.referrer_level = (ref.referrer_level or 0) + 1
            await session.flush()
            # уведомить реферера о новом реферале 1 уровня
            await _notify_referrer_new(bot, session, ref.id, db_user, level=1)

    # уведомление админам о новом юзере
    if is_new:
        ref_text = ""
        if db_user.referrer_id:
            ref_text = f"\n🔗 От реферера #{db_user.referrer_id}"
        await notify_admins(
            bot,
            session,
            f"🆕 <b>Новый пользователь</b>\n\n"
            f"👤 {db_user.full_name or '—'}\n"
            f"🆔 TG: <code>{db_user.telegram_id}</code>\n"
            f"📛 @{db_user.username or '—'}"
            f"{ref_text}",
        )

    # Для не-админов: сперва проверяем подписку. Если не подписан —
    # показываем ТОЛЬКО экран подписки (без главного меню).
    # Главное меню придёт только после нажатия «Я подписался» и успешной проверки.
    if not is_admin:
        try:
            from src.middlewares.subscription import SubscriptionMiddleware
            from src.database.repositories import DepositsRepo, SettingsRepo
            from src.database.models import Deposit, DepositStatus
            from sqlalchemy import func, select

            srepo = SettingsRepo(session)
            ch_id = await srepo.get("required_channel_id", "")
            ch_url = await srepo.get("required_channel_url", "")
            gr_id = await srepo.get("required_group_id", "")
            gr_url = await srepo.get("required_group_url", "")
            ch_legacy = await srepo.get("required_channel", "") or get_settings().required_channel
            gr_legacy = await srepo.get("required_group", "") or get_settings().required_group
            inv_id = await srepo.get("investors_group_id", "")
            inv_url = await srepo.get("investors_group_url", "") or await srepo.get("investors_group_invite", "")

            check_channel = ch_id or ch_legacy
            check_group = gr_id or gr_legacy
            show_channel = ch_url or ch_legacy
            show_group = gr_url or gr_legacy

            # Группа вкладчиков — только если у юзера есть активный/завершённый депозит
            check_investors = ""
            show_investors = ""
            if inv_id:
                res = await session.execute(
                    select(func.count(Deposit.id)).where(
                        Deposit.user_id == db_user.id,
                        Deposit.status.in_([
                            DepositStatus.ACTIVE.value,
                            DepositStatus.COMPLETED.value,
                        ]),
                    )
                )
                if int(res.scalar_one()) > 0:
                    check_investors = inv_id
                    show_investors = inv_url

            if check_channel or check_group or check_investors:
                mw = SubscriptionMiddleware()
                if not await mw._is_subscribed(
                    bot, db_user.telegram_id, check_channel, check_group, check_investors
                ):
                    kb = mw._build_keyboard(
                        db_user.lang, show_channel, show_group, show_investors
                    )
                    await message.answer(
                        i18n.t("subscribe.required.title", db_user.lang),
                        reply_markup=kb,
                    )
                    return
        except Exception as e:
            logger.warning("post-/start subscription probe failed: %s", e)

    await message.answer(
        i18n.t("start.welcome", db_user.lang, name=db_user.full_name or "друг"),
        reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
    )


async def _notify_referrer_new(
    bot: Bot, session: AsyncSession, referrer_id: int, new_user: User, level: int
) -> None:
    from aiogram.exceptions import TelegramAPIError

    ref = await UsersRepo(session).get_by_id(referrer_id)
    if ref is None:
        return
    who = f"@{new_user.username}" if new_user.username else (new_user.full_name or f"id:{new_user.telegram_id}")
    try:
        from src.keyboards.common import home_kb

        await bot.send_message(
            ref.telegram_id,
            i18n.t("referrals.notify_new", ref.lang, who=who, level=level),
            reply_markup=home_kb(ref.lang),
        )
    except TelegramAPIError:
        pass


@router.callback_query(F.data == "menu:home", StateFilter(any_state))
async def cb_home(cb: CallbackQuery, db_user: User, is_admin: bool, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.edit_text(
            i18n.t("start.welcome", db_user.lang, name=db_user.full_name or "друг"),
            reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            i18n.t("start.welcome", db_user.lang, name=db_user.full_name or "друг"),
            reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
        )
    await cb.answer()


@router.callback_query(F.data == "menu:lang", StateFilter(any_state))
@router.message(Command("lang"), StateFilter(any_state))
async def lang_cmd(event: Message | CallbackQuery, db_user: User, state: FSMContext) -> None:
    await state.clear()
    text = i18n.t("start.lang_choose", db_user.lang)
    kb = lang_kb()
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def set_lang(cb: CallbackQuery, db_user: User, session: AsyncSession, is_admin: bool) -> None:
    lang = cb.data.split(":")[1]
    if lang not in ("ru", "kg"):
        await cb.answer()
        return
    users = UsersRepo(session)
    await users.update_lang(db_user.id, lang)
    db_user.lang = lang
    await cb.message.edit_text(
        i18n.t("lang.changed", lang),
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )
    await cb.answer()


@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery, db_user: User, is_admin: bool) -> None:
    # Сама middleware либо пропустит запрос (если подписан), либо снова
    # покажет экран подписки. Сюда мы доходим только если подписка ок.
    try:
        await cb.message.edit_text(
            i18n.t("start.welcome", db_user.lang, name=db_user.full_name or "друг"),
            reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            i18n.t("start.welcome", db_user.lang, name=db_user.full_name or "друг"),
            reply_markup=main_menu_kb(db_user.lang, is_admin=is_admin),
        )
    await cb.answer("✅ Доступ открыт")
