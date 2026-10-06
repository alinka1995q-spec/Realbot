import asyncio
import logging

import uvicorn
from src.bot import run as run_bot
from src.admin.app import app as admin_app

logger = logging.getLogger(__name__)


async def main():
    """Запускаем веб админку и Telegram бота параллельно."""
    # Настраиваем uvicorn server
    config = uvicorn.Config(admin_app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    # Запускаем веб админку и бота параллельно
    bot_task = asyncio.create_task(run_bot())
    server_task = asyncio.create_task(server.serve())

    try:
        await asyncio.gather(bot_task, server_task)
    except asyncio.CancelledError:
        logger.info("Shutting down")


if __name__ == "__main__":
    asyncio.run(main())

