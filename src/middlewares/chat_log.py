"""Журналирование сообщений пользователя в БД (для просмотра в админке)."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from src.database.models import UserChatMessage


class ChatLogMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            db_user = data.get("db_user")
            session = data.get("session")
            if db_user is not None and session is not None:
                media = None
                if event.photo:
                    media = "photo"
                elif event.video:
                    media = "video"
                elif event.document:
                    media = "document"
                session.add(
                    UserChatMessage(
                        user_id=db_user.id,
                        direction="in",
                        text=event.text or event.caption,
                        media_type=media,
                    )
                )
        return await handler(event, data)
