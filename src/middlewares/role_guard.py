"""Middleware для админ-callback'ов: модератор имеет доступ только к депозитам."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

# Префиксы callback_data, разрешённые модератору
MODERATOR_ALLOWED_PREFIXES = (
    "admin:menu",
    "adm:menu",
    "adm:deposits",        # список депозитов и табы
    "adm:dep:show:",       # карточка
    "adm:dep:ok:",         # подтвердить (запрос)
    "adm:dep:ok_yes:",     # подтвердить (финал)
    "adm:dep:no:",         # отклонить (запрос причины)
    "adm:dep:no_yes:",     # отклонить (финал)
    "adm:dep:edit:",       # меню редактирования реквизитов
    "adm:dep:setbank:",    # изменить банк
    "adm:dep:setnum:",     # изменить номер
    "adm:dep:setfio:",     # изменить ФИО
    "adm:dep:editfield:",  # подтверждение сохранения
    "adm:dep:editfield:yes:",  # финальное применение
    "menu:",
    "check_sub",
    "lang:",
)

# Действия с депозитом, НЕдоступные модератору (нужны полные права)
MODERATOR_DENIED_DEPOSIT_PREFIXES = (
    "adm:dep:amt:",     # изменение суммы
    "adm:dep:close:",   # досрочное закрытие
    "adm:dep:pay:",     # ручная выплата
)


def _is_moderator_allowed(cb_data: str) -> bool:
    """Можно ли модератору вызвать этот callback."""
    if any(cb_data.startswith(p) for p in MODERATOR_DENIED_DEPOSIT_PREFIXES):
        return False
    return any(cb_data.startswith(p) for p in MODERATOR_ALLOWED_PREFIXES)


class RoleGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        is_admin = data.get("is_admin", False)
        is_full = data.get("is_full_admin", False)

        # full admin или не-админ - пропускаем без ограничений
        if is_full or not is_admin:
            return await handler(event, data)

        # модератор: проверяем callback
        if isinstance(event, CallbackQuery) and event.data:
            if event.data.startswith("adm:") or event.data.startswith("admin:"):
                if not _is_moderator_allowed(event.data):
                    await event.answer("⛔ Доступно только администратору", show_alert=True)
                    return None

        return await handler(event, data)
