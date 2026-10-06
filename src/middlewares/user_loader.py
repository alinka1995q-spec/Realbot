from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from src.database.repositories import AdminsRepo, UsersRepo


class UserLoaderMiddleware(BaseMiddleware):
    """Грузит/создаёт user из БД и кладёт его + признак админа в data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        session = data["session"]
        users = UsersRepo(session)
        admins = AdminsRepo(session)

        full_name = (tg_user.full_name or "").strip() or None
        user, is_new = await users.get_or_create(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=full_name,
            lang=tg_user.language_code or "ru",
        )

        data["db_user"] = user
        data["is_new_user"] = is_new
        admin = await admins.get_by_tg(tg_user.id)
        data["is_admin"] = admin is not None
        data["admin_role"] = (admin.role if admin else None)
        data["is_full_admin"] = bool(admin and (admin.is_root or admin.role == "admin"))
        return await handler(event, data)
