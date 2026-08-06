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
                           action: str, duration: int | None, settings: dict,
                           expiry: int | None = None) -> str:
    """Применяет наказание. Возвращает человекочитаемый результат.

    expiry — для action='warn': абсолютная метка времени, когда варн
    автоматически снимется (None — пока не соберётся лимит).
    """
    if action == "mute":
        # Мут никогда не навсегда: минимум 1 час, максимум 24 часа.
        if not duration or duration > 24 * 3600:
            duration = min(duration or 3600, 24 * 3600)
        until = int(time.time()) + duration
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        return f"Мут на {format_duration(duration)}"

    if action == "ban":
        # Бан: максимум 14 дней, либо навсегда (duration=None).
        if duration and duration > 14 * 24 * 3600:
            duration = 14 * 24 * 3600
        until = int(time.time()) + duration if duration else None
        await bot.ban_chat_member(chat_id, user_id, until_date=until)
        return f"Бан на {format_duration(duration)}"

    if action == "kick":
        await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
        await bot.unban_chat_member(chat_id, user_id)
        return "Кик"

    if action == "warn":
        count = await storage.add_warning(chat_id, user_id, expiry)
        limit = int(settings.get("warn_limit", 3))
        if count >= limit:
            await storage.reset_warnings(chat_id, user_id)
            await bot.ban_chat_member(chat_id, user_id)
            return f"Варн {count}/{limit} — бан навсегда"
        if expiry:
            left = max(0, int(expiry) - int(time.time()))
            return f"Варн {count}/{limit} · снимется через {format_duration(left)}"
        return f"Варн {count}/{limit}"

    return "Наказание не найдено"


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
