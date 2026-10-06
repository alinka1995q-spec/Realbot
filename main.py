import asyncio
import logging
import threading

import uvicorn
from src.bot import run as run_bot
from src.admin.app import app as admin_app

logger = logging.getLogger(__name__)


def run_bot_in_thread():
    """Запуск бота в отдельном потоке."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except Exception:
        logger.exception("Bot error")
    finally:
        loop.close()


def run_web_server():
    """Запуск веб сервера в основном потоке."""
    uvicorn.run(admin_app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    # Запускаем бота в отдельном потоке (демон)
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")

    # Веб сервер в основном потоке
    logger.info("Starting web server")
    run_web_server()

