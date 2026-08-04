"""Точка входа: запуск бота (polling). Запуск: python bot.py"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import BOT_TOKEN
from src.handlers_group import router as group_router
from src.handlers_private import router as private_router
from src.moderation import Trackers
from src.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан! Получи токен у @BotFather.")

    storage = Storage()
    await storage.connect()
    trackers = Trackers()

    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    dp["storage"] = storage
    dp["trackers"] = trackers

    dp.include_router(private_router)
    dp.include_router(group_router)

    me = await bot.get_me()
    logging.info("Бот запущен: @%s (id %s)", me.username, me.id)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member"])


if __name__ == "__main__":
    asyncio.run(main())
