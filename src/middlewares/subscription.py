"""Проверка подписки на обязательные каналы/группы (для пользовательских команд).

Если пользователь админ - пропускаем без проверки.
Если пользователь не подписан - показываем экран с кнопками-ссылками и кнопкой «Я подписался».
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from src.config import get_settings
from src.database.repositories import SettingsRepo
from src.i18n import i18n

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {"member", "creator", "administrator", "restricted"}
# check_sub НЕ освобождён - middleware должен заново проверить подписку перед
# тем как пропустить юзера в главное меню.
EXEMPT_CALLBACKS = {"lang:ru", "lang:kg", "menu:lang"}
# /start больше не освобождён - если юзер не подписан, ему сразу должен
# показаться экран подписки, а не главное меню.
EXEMPT_COMMANDS = {"/lang", "/admin"}


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # пропускаем админов
        if data.get("is_admin"):
            return await handler(event, data)

        # Извлекаем Message / CallbackQuery — middleware повешен на dp.update,
        # event может быть как Update, так и уже распакованным объектом
        msg: Message | None = None
        cb: CallbackQuery | None = None
        if isinstance(event, Message):
            msg = event
        elif isinstance(event, CallbackQuery):
            cb = event
        else:
            inner = getattr(event, "message", None) or getattr(event, "callback_query", None)
            if isinstance(inner, Message):
                msg = inner
            elif isinstance(inner, CallbackQuery):
                cb = inner

        # /start всегда пропускаем — приветствие важнее, чем экран подписки
        # (после /start юзер увидит main menu, а при попытке любой функции
        #  middleware снова проверит подписку)
        if msg and msg.text and msg.text.split()[0] == "/start":
            return await handler(event, data)

        if cb and cb.data and cb.data in EXEMPT_CALLBACKS:
            return await handler(event, data)
        if msg and msg.text and msg.text.split()[0] in EXEMPT_COMMANDS:
            return await handler(event, data)

        bot: Bot = data["bot"]
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # читаем актуальные каналы из БД (с fallback на .env)
        # Приоритет: новые ключи (_id + _url), затем legacy required_channel/group
        session = data.get("session")
        inv_id = ""
        inv_url = ""
        inv_legacy = ""
        if session is not None:
            srepo = SettingsRepo(session)
            ch_id = await srepo.get("required_channel_id", "")
            ch_url = await srepo.get("required_channel_url", "")
            gr_id = await srepo.get("required_group_id", "")
            gr_url = await srepo.get("required_group_url", "")
            inv_id = await srepo.get("investors_group_id", "")
            inv_url = await srepo.get("investors_group_url", "")
            inv_legacy = await srepo.get("investors_group_invite", "")
            # fallback на старые ключи (если новых нет)
            ch_legacy = await srepo.get("required_channel", "") or self.settings.required_channel
            gr_legacy = await srepo.get("required_group", "") or self.settings.required_group
        else:
            ch_id = ""
            ch_url = ""
            gr_id = ""
            gr_url = ""
            ch_legacy = self.settings.required_channel
            gr_legacy = self.settings.required_group

        # Что проверять (для get_chat_member): новый chat_id → fallback legacy
        check_channel = ch_id or ch_legacy
        check_group = gr_id or gr_legacy
        # Что показывать на кнопке: новый url → fallback legacy
        show_channel = ch_url or ch_legacy
        show_group = gr_url or gr_legacy
        # Группа вкладчиков — проверяется только для юзеров с подтв. депозитом
        db_user = data.get("db_user")
        require_investors = False
        if inv_id and db_user is not None and session is not None:
            from src.database.repositories import DepositsRepo
            from src.database.models import Deposit, DepositStatus
            from sqlalchemy import select, func
            res = await session.execute(
                select(func.count(Deposit.id)).where(
                    Deposit.user_id == db_user.id,
                    Deposit.status.in_([
                        DepositStatus.ACTIVE.value,
                        DepositStatus.COMPLETED.value,
                    ]),
                )
            )
            require_investors = int(res.scalar_one()) > 0
        check_investors = inv_id if require_investors else ""
        show_investors = inv_url or inv_legacy if require_investors else ""

        if not (check_channel or check_group or check_investors):
            return await handler(event, data)

        if await self._is_subscribed(
            bot, user.id, check_channel, check_group, check_investors
        ):
            return await handler(event, data)

        # не подписан - показываем экран
        lang = db_user.lang if db_user else self.settings.default_lang
        kb = self._build_keyboard(lang, show_channel, show_group, show_investors)
        text = i18n.t("subscribe.required.title", lang)

        if cb:
            try:
                await cb.message.edit_text(text, reply_markup=kb)
            except TelegramBadRequest:
                await cb.message.answer(text, reply_markup=kb)
            await cb.answer()
        elif msg:
            await msg.answer(text, reply_markup=kb)
        return None

    async def _is_subscribed(
        self,
        bot: Bot,
        user_id: int,
        channel: str = "",
        group: str = "",
        investors: str = "",
    ) -> bool:
        targets = [c for c in (channel, group, investors) if c]
        for chat in targets:
            chat_ref = self._resolve_chat_ref(chat)
            if chat_ref is None:
                # инвайт-ссылка - проверить нельзя, считаем что не подписан
                logger.error(
                    "Subscription check impossible for %r (invite link). "
                    "Use @username or numeric chat_id and add the bot as admin.",
                    chat,
                )
                return False
            try:
                member = await bot.get_chat_member(chat_ref, user_id)
                if member.status not in ALLOWED_STATUSES:
                    return False
            except TelegramBadRequest as e:
                logger.error(
                    "Subscription check failed for user %s in %r: %s. "
                    "Make sure chat exists and bot is admin.",
                    user_id, chat_ref, e,
                )
                return False
            except Exception as e:
                logger.exception("Subscription error: %s", e)
                return False
        return True

    @staticmethod
    def _resolve_chat_ref(chat: str) -> str | int | None:
        """Возвращает то, что можно передать в get_chat_member.

        - "@username"  -> "@username"
        - "username"   -> "@username"
        - "-1001234"   -> -1001234
        - "https://t.me/joinchat/..." / "https://t.me/+..." -> None (инвайт-ссылка, проверить нельзя)
        - "https://t.me/username" -> "@username"
        """
        c = chat.strip()
        if not c:
            return None
        if c.startswith("@"):
            return c
        if c.startswith("-") and c[1:].isdigit():
            return int(c)
        if c.isdigit():
            return int(c)
        if c.startswith("http"):
            # https://t.me/+abc... или https://t.me/joinchat/... -> приват-инвайт
            tail = c.split("t.me/", 1)[-1] if "t.me/" in c else c
            if tail.startswith("+") or tail.startswith("joinchat/"):
                return None
            # https://t.me/username
            handle = tail.split("/", 1)[0].split("?", 1)[0]
            return f"@{handle}" if handle else None
        return f"@{c}"

    def _build_keyboard(
        self, lang: str, channel: str = "", group: str = "", investors: str = ""
    ) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if channel:
            url = self._chat_url(channel)
            rows.append([InlineKeyboardButton(text=i18n.t("subscribe.required.btn_channel", lang), url=url)])
        if group:
            url = self._chat_url(group)
            rows.append([InlineKeyboardButton(text=i18n.t("subscribe.required.btn_group", lang), url=url)])
        if investors:
            url = self._chat_url(investors)
            rows.append([InlineKeyboardButton(
                text=i18n.t("subscribe.investors.btn", lang), url=url
            )])
        rows.append(
            [InlineKeyboardButton(text=i18n.t("subscribe.required.btn_check", lang), callback_data="check_sub")]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def _chat_url(chat: str) -> str:
        if chat.startswith("@"):
            return f"https://t.me/{chat[1:]}"
        if chat.startswith("http"):
            return chat
        return f"https://t.me/{chat}"
