"""Точка входа: запуск бота (polling). Запуск: python bot.py"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import BOT_API_BASE_URL, BOT_PROXY, BOT_TOKEN
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

    api = TelegramAPIServer.from_base(BOT_API_BASE_URL)
    session = AiohttpSession(proxy=BOT_PROXY, api=api) if BOT_PROXY else AiohttpSession(api=api)
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["storage"] = storage
    dp["trackers"] = trackers

    dp.include_router(private_router)
    dp.include_router(group_router)

    me = await bot.get_me()
    logging.info("Бот запущен: @%s (id %s) через %s", me.username, me.id, BOT_API_BASE_URL)
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"],
        polling_timeout=25,
    )


if __name__ == "__main__":
    asyncio.run(main())
