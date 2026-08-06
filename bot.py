"""Точка входа: запуск бота (polling). Запуск: python bot.py"""

import asyncio
import logging
import os
import sys

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

_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot.lock")


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с данным PID (Windows/Linux)."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock() -> None:
    """Не даём запустить второй экземпляр бота (иначе конфликт getUpdates и потеря апдейтов)."""
    if os.path.exists(_LOCK_FILE):
        try:
            with open(_LOCK_FILE, encoding="utf-8") as f:
                old_pid = int(f.read().strip())
        except (OSError, ValueError):
            old_pid = -1
        if old_pid > 0 and _pid_alive(old_pid):
            raise SystemExit(
                f"Бот уже запущен (PID {old_pid}). Закрой старое окно/процесс и попробуй снова."
            )
    with open(_LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан! Получи токен у @BotFather.")

    _acquire_lock()

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
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"],
            polling_timeout=25,
        )
    finally:
        if os.path.exists(_LOCK_FILE):
            try:
                os.remove(_LOCK_FILE)
            except OSError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
