import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent

from src.config import get_settings
from src.database import async_session_factory, init_models
from src.database.repositories import AdminsRepo, SettingsRepo, TextsRepo
from src.handlers import all_routers
from src.i18n import i18n
from src.middlewares import (
    ChatLogMiddleware,
    DbSessionMiddleware,
    RoleGuardMiddleware,
    SubscriptionMiddleware,
    UserLoaderMiddleware,
)
from src.scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def bootstrap() -> None:
    """Создаём таблицы, root-админа и подгружаем тексты."""
    await init_models()

    settings = get_settings()
    async with async_session_factory() as session:
        admins = AdminsRepo(session)
        if not await admins.is_admin(settings.root_admin_id):
            await admins.add(settings.root_admin_id, name="Root", is_root=True)
            await session.commit()

        # подгружаем оверрайды текстов из БД
        texts = TextsRepo(session)
        keys = await texts.keys()
        overrides: list[tuple[str, str, str]] = []
        for k in keys:
            for lang in ("ru", "kg"):
                v = await texts.get(k, lang)
                if v is not None:
                    overrides.append((k, lang, v))
        i18n.reload_overrides(overrides)


async def run() -> None:
    settings = get_settings()
    await bootstrap()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    if settings.redis_url:
        storage = RedisStorage.from_url(settings.redis_url)
        logger.info("FSM storage: Redis")
    else:
        storage = MemoryStorage()
        logger.info("FSM storage: Memory (REDIS_HOST not set)")
    dp = Dispatcher(storage=storage)

    # порядок middleware важен: session → user_loader → chat_log → subscription → role_guard
    dp.update.outer_middleware(DbSessionMiddleware(async_session_factory))
    dp.update.outer_middleware(UserLoaderMiddleware())
    dp.message.outer_middleware(ChatLogMiddleware())
    dp.update.outer_middleware(SubscriptionMiddleware())
    dp.update.outer_middleware(RoleGuardMiddleware())

    for router in all_routers():
        dp.include_router(router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        exc = event.exception
        logger.exception("Unhandled error: %s", exc)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3500:]
        try:
            await bot.send_message(
                settings.root_admin_id,
                f"🛑 <b>Системная ошибка</b>\n<pre>{tb}</pre>",
            )
        except Exception:
            pass
        return True

    scheduler = build_scheduler(bot)
    scheduler.start()

    me = await bot.get_me()
    logger.info("Bot @%s (id=%s) started", me.username, me.id)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
