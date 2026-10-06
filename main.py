import asyncio
import logging
from contextlib import suppress

import uvicorn
from src.bot import run
from src.admin.app import app as admin_app

logger = logging.getLogger(__name__)


async def run_bot():
    """Запуск Telegram бота."""
    try:
        await run()
    except asyncio.CancelledError:
        logger.info("Bot cancelled")
    except Exception:
        logger.exception("Bot error")


if __name__ == "__main__":
    # Запускаем веб админку на порту 8000 и бота параллельно
    import threading

    # Бот в отдельном потоке
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()), daemon=True)
    bot_thread.start()

    # Веб админка в основном потоке
    uvicorn.run(admin_app, host="0.0.0.0", port=8000, log_level="info")

