"""Выполнение наказаний и детекторы флуда/спама."""

import time

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions

from .rules import format_duration

SEVERITY_ORDER = {"warn": 1, "kick": 2, "mute": 3, "ban": 4}


async def get_member_status(bot, chat_id: int, user_id: int) -> str | None:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status
    except Exception:
        return None


async def is_protected(bot, chat_id: int, user_id: int) -> bool:
    """Админы/владелец чата — защищены от наказаний."""
    status = await get_member_status(bot, chat_id, user_id)
    return status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def apply_punishment(bot, storage, chat_id: int, user_id: int,
                           action: str, duration: int | None, settings: dict) -> str:
    """Применяет наказание. Возвращает человекочитаемый результат."""
    if action == "mute":
        until = int(time.time()) + duration if duration else None
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        return f"🔇 мут {format_duration(duration)}"

    if action == "ban":
        until = int(time.time()) + duration if duration else None
        await bot.ban_chat_member(chat_id, user_id, until_date=until)
        return f"⛔️ бан {format_duration(duration)}"

    if action == "kick":
        await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
        await bot.unban_chat_member(chat_id, user_id)
        return "👢 кик"

    if action == "warn":
        count = await storage.add_warning(chat_id, user_id)
        limit = int(settings.get("warn_limit", 3))
        if count >= limit:
            await storage.reset_warnings(chat_id, user_id)
            mute_min = int(settings.get("warn_mute_min", 60))
            until = int(time.time()) + mute_min * 60
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            return f"⚠️ {count}/{limit} варнов → 🔇 мут {mute_min} мин"
        return f"⚠️ варн {count}/{limit}"

    return "🤔 наказание не найдено"


class Trackers:
    """In-memory детекторы флуда и повторов (сбрасываются при рестарте)."""

    def __init__(self) -> None:
        self.flood: dict[int, dict[int, list[float]]] = {}
        self.spam: dict[int, dict[int, dict]] = {}

    def check_flood(self, chat_id: int, user_id: int, limit: int, window: int) -> bool:
        ts = time.time()
        arr = self.flood.setdefault(chat_id, {}).setdefault(user_id, [])
        arr.append(ts)
        cutoff = ts - window
        arr[:] = [t for t in arr if t > cutoff]
        return len(arr) >= limit

    def check_spam(self, chat_id: int, user_id: int, text: str, limit: int, window: int) -> bool:
        ts = time.time()
        entry = self.spam.setdefault(chat_id, {}).setdefault(
            user_id, {"text": None, "count": 0, "last": 0.0}
        )
        if entry["text"] == text and ts - entry["last"] <= window:
            entry["count"] += 1
            entry["last"] = ts
            return entry["count"] >= limit
        entry["text"] = text
        entry["count"] = 1
        entry["last"] = ts
        return False
