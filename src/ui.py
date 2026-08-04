"""Красивые клавиатуры и тексты интерфейса."""

from html import escape as _esc

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def esc(value) -> str:
    """Экранирование HTML в пользовательских строках."""
    return _esc(str(value), quote=False)

WELCOME_TEXT = (
    "👋 Привет, босс!\n\n"
    "Я — <b>ModeratorBot</b> — твой личный модератор для Telegram-чатов 🤖\n\n"
    "Что я умею:\n"
    "🔹 Слежу за чатами 24/7 по твоим правилам\n"
    "🔹 Мгновенно наказываю за флуд, рекламу, мат и другое\n"
    "🔹 Работаю сразу в нескольких чатах\n"
    "🔹 Отвечаю только тебе — остальных игнорирую\n\n"
    "Нажми кнопку, чтобы начать 👇"
)

HELP_TEXT = (
    "📖 <b>Помощь</b>\n\n"
    "<b>Как подключить чат:</b>\n"
    "1️⃣ Добавь меня в свой чат\n"
    "2️⃣ Назначь меня администратором (дать все права)\n"
    "3️⃣ Нажми «➕ Добавить чат» и выбери чат\n"
    "4️⃣ Добавь правила через «➕ Добавить правило»\n\n"
    "<b>Формат правила:</b>\n"
    "<code>нарушение - наказание</code>\n\n"
    "Примеры:\n"
    "• <code>флуд - мут 1 час</code>\n"
    "• <code>реклама - бан</code>\n"
    "• <code>мат - мут 30 минут</code>\n"
    "• <code>слово:айпи - кик</code>\n"
    "• <code>спам - мут 2 часа</code>\n\n"
    "Наказания: 🔇 мут, ⛔️ бан, 👢 кик, ⚠️ варн.\n"
    "Длительность: 30 минут, 2 часа, 1 день, навсегда.\n\n"
    "В чате также работают команды:\n"
    "<code>/mute</code>, <code>/ban</code>, <code>/kick</code>, "
    "<code>/warn</code>, <code>/unmute</code>, <code>/unban</code>, "
    "<code>/rules</code>, <code>/addrule</code>, <code>/delrule</code>"
)


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📜 Правила", callback_data="menu:rules")
    b.button(text="➕ Добавить чат", callback_data="menu:addchat")
    b.button(text="➕ Добавить правило", callback_data="menu:addrule")
    b.button(text="⚙️ Настройки", callback_data="menu:settings")
    b.button(text="❌ Удалить чат", callback_data="menu:delchat")
    b.adjust(2)
    return b.as_markup()


def chat_list_keyboard(chats: list[dict], action: str, back: str = "back:menu") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in chats:
        title = (c.get("title") or f"чат {c.get('chat_id')}")[:40]
        mark = "✅" if c.get("enabled") else "⬜️"
        b.button(text=f"{mark} {title}", callback_data=f"{action}:{c['chat_id']}")
    b.button(text="🔙 Назад", callback_data=back)
    b.adjust(1)
    return b.as_markup()


def rules_keyboard(rules: list[dict], chat_id: int, enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rules:
        from .rules import Rule

        rule = Rule.from_dict(r)
        b.button(
            text=f"✖️ {r['id']} · {rule.to_display()}",
            callback_data=f"delrule:{r['id']}",
        )
    b.button(text="➕ Добавить правило", callback_data=f"addrule2:{chat_id}")
    b.button(
        text="⏸ На паузу" if enabled else "▶️ Включить",
        callback_data=f"togglechat:{chat_id}",
    )
    b.button(text="⚙️ Настройки", callback_data=f"settings:{chat_id}")
    b.button(text="🔙 Назад", callback_data="menu:rules")
    b.adjust(1)
    return b.as_markup()


def settings_text(s: dict, chat: dict | None) -> str:
    title = esc((chat and chat.get("title")) or s["chat_id"])
    on = lambda v: "✅" if v else "❌"  # noqa: E731
    return (
        f"⚙️ Настройки чата «{title}»\n\n"
        f"🗑 Удалять нарушение: {on(s['delete_on_violation'])}\n"
        f"🔔 Уведомлять в чате: {on(s['notify_group'])}\n"
        f"👮 Наказывать админов: {on(s['punish_admins'])}\n"
        f"⚠️ Лимит варнов: {s['warn_limit']}\n"
        f"🔇 Мут после лимита варнов: {s['warn_mute_min']} мин\n"
        f"🌊 Флуд: {s['flood_messages']} сообщ. за {s['flood_seconds']} сек\n"
        f"🔁 Спам: {s['spam_messages']} повтора за {s['spam_seconds']} сек"
    )


def settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    cid = s["chat_id"]
    b = InlineKeyboardBuilder()
    b.button(
        text=f"🗑 Удалять нарушение: {'✅' if s['delete_on_violation'] else '❌'}",
        callback_data=f"set:{cid}:delete_on_violation:{1 - s['delete_on_violation']}",
    )
    b.button(
        text=f"🔔 Уведомлять в чате: {'✅' if s['notify_group'] else '❌'}",
        callback_data=f"set:{cid}:notify_group:{1 - s['notify_group']}",
    )
    b.button(
        text=f"👮 Наказывать админов: {'✅' if s['punish_admins'] else '❌'}",
        callback_data=f"set:{cid}:punish_admins:{1 - s['punish_admins']}",
    )
    b.button(text="⚠️ Варн −", callback_data=f"set:{cid}:warn_limit:{max(1, s['warn_limit'] - 1)}")
    b.button(text="⚠️ Варн +", callback_data=f"set:{cid}:warn_limit:{min(10, s['warn_limit'] + 1)}")
    b.button(text="🔇 Мут-мин −", callback_data=f"set:{cid}:warn_mute_min:{max(1, s['warn_mute_min'] - 5)}")
    b.button(text="🔇 Мут-мин +", callback_data=f"set:{cid}:warn_mute_min:{min(1440, s['warn_mute_min'] + 5)}")
    b.button(text="🌊 Флуд −", callback_data=f"set:{cid}:flood_messages:{max(2, s['flood_messages'] - 1)}")
    b.button(text="🌊 Флуд +", callback_data=f"set:{cid}:flood_messages:{min(30, s['flood_messages'] + 1)}")
    b.button(text="🌊 Окно −", callback_data=f"set:{cid}:flood_seconds:{max(5, s['flood_seconds'] - 5)}")
    b.button(text="🌊 Окно +", callback_data=f"set:{cid}:flood_seconds:{min(120, s['flood_seconds'] + 5)}")
    b.button(text="🔁 Спам −", callback_data=f"set:{cid}:spam_messages:{max(2, s['spam_messages'] - 1)}")
    b.button(text="🔁 Спам +", callback_data=f"set:{cid}:spam_messages:{min(20, s['spam_messages'] + 1)}")
    b.button(text="🔁 Окно −", callback_data=f"set:{cid}:spam_seconds:{max(5, s['spam_seconds'] - 5)}")
    b.button(text="🔁 Окно +", callback_data=f"set:{cid}:spam_seconds:{min(120, s['spam_seconds'] + 5)}")
    b.button(text="🔙 Назад", callback_data="back:menu")
    b.adjust(1)
    return b.as_markup()
