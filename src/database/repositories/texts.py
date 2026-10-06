from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import BotText


class TextsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, lang: str) -> Optional[str]:
        res = await self.session.execute(
            select(BotText.value).where(BotText.key == key, BotText.lang == lang)
        )
        return res.scalar_one_or_none()

    async def set(self, key: str, lang: str, value: str) -> None:
        existing = await self.session.execute(
            select(BotText.id).where(BotText.key == key, BotText.lang == lang)
        )
        row_id = existing.scalar_one_or_none()
        if row_id is None:
            self.session.add(BotText(key=key, lang=lang, value=value))
        else:
            await self.session.execute(
                update(BotText).where(BotText.id == row_id).values(value=value)
            )

    async def all_by_lang(self, lang: str) -> dict[str, str]:
        res = await self.session.execute(select(BotText.key, BotText.value).where(BotText.lang == lang))
        return {row[0]: row[1] for row in res}

    async def keys(self) -> list[str]:
        res = await self.session.execute(select(BotText.key).distinct().order_by(BotText.key))
        return [row[0] for row in res]
