"""Красивые клавиатуры и тексты интерфейса (без эмодзи)."""

from html import escape as _esc

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def esc(value) -> str:
    """Экранирование HTML в пользовательских строках."""
    return _esc(str(value), quote=False)


DEFAULT_GREETING = (
    "Привет, {name}! Добро пожаловать в чат «{chat}»! "
    "Здесь дружелюбная компания и свои правила — загляни в них, "
    "и приятного общения!"
)


def chat_open_link(chat) -> str | None:
    """Ссылка на чат. Для супергрупп без username работает t.me/c/<id>."""
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}"
    cid = getattr(chat, "id", None)
    if isinstance(cid, int) and cid < -1000000000000:
        return f"https://t.me/c/{abs(cid) - 1000000000000}"
    return None


def render_greeting(template: str, name: str, username: str, chat_title: str,
                    *, user_id: int | None = None, chat=None) -> str:
    """Подставляет имя, ник и название чата в шаблон приветствия.

    {name} и {username} становятся ссылками на аккаунт (tg://user?id=),
    {chat} — ссылкой на чат (t.me/<username> или t.me/c/<id>).
    Все пользовательские значения экранируются, шаблон считается доверенным.
    """
    name_part = esc(name) if name else ""
    if user_id:
        name_part = f'<a href="tg://user?id={int(user_id)}">{name_part}</a>'

    user_part = esc(username) if username else ""
    if user_id and username:
        user_part = f'<a href="tg://user?id={int(user_id)}">{user_part}</a>'

    title_part = esc(chat_title) if chat_title else "наш чат"
    link = chat_open_link(chat) if chat is not None else None
    if link and chat_title:
        title_part = f'<a href="{link}">{title_part}</a>'

    return (
        template.replace("{name}", name_part)
        .replace("{username}", user_part)
        .replace("{chat}", title_part)
    )


WELCOME_TEXT = (
    "<b>Привет, босс!</b>\n\n"
    "Я — <b>desacratio Helper</b> — твой персональный модератор для Telegram-чатов.\n\n"
    "<b>Что я умею:</b>\n"
    "• Слежу за чатами 24/7 по твоим правилам\n"
    "• Ловлю флуд, спам, рекламу, мат, капс и эмодзи-флуд\n"
    "• Умею работать с несколькими чатами сразу\n"
    "• Отвечаю только тебе — остальных игнорирую\n\n"
    "Нажми кнопку, чтобы начать"
)

HELP_TEXT = (
    "<b>Помощь</b>\n\n"
    "<b>Как подключить чат:</b>\n"
    "1. Добавь меня в свой чат\n"
    "2. Назначь меня <b>администратором</b> (дай все права)\n"
    "3. Нажми «Добавить чат» и выбери чат\n"
    "4. Добавь правила через «Добавить правило»\n\n"
    "<b>Формат правила:</b>\n"
    "<code>нарушение - наказание</code>\n\n"
    "<b>Примеры:</b>\n"
    "• <code>флуд - мут 1 час</code>\n"
    "• <code>реклама - бан</code>\n"
    "• <code>мат - мут 30 минут</code>\n"
    "• <code>слово:айпи - кик</code>\n"
    "• <code>спам - мут 2 часа</code>\n\n"
    "Можно отправить <b>целый блок правил</b> — я разберу каждую строку сам!\n\n"
    "<b>Наказания:</b>\n"
    "<b>мут</b> · <b>бан</b> · <b>кик</b> · <b>варн</b>\n\n"
    "<b>Длительность:</b> 30 минут, 2 часа, 1 день, навсегда…\n\n"
    "<b>В чате работают команды (ответь на сообщение нарушителя или укажи @username/id):</b>\n"
    "<code>/bban время причина</code> — бан\n"
    "<code>/mmute время причина</code> — мут\n"
     "<code>/kkick причина</code> — кик (не бан — может вернуться)\n"
    "<code>/wwarn время причина</code> — предупреждение\n\n"
     "<b>Снять наказание (ответом или @username/id):</b>\n"
     "<code>/unbban</code> <code>/unmmute</code> <code>/unkkick</code> <code>/unwwarn</code>\n\n"
     "<b>После трёх предупреждений — бан навсегда.</b> "
     "Предупреждения автоматически снимаются, если указать время.\n\n"
     "<b>Конкурс комментариев:</b>\n"
     "<code>/reward 44</code> — до 44-го комментария бот не трогает флуд и спам\n"
     "<code>/rewardstop</code> — остановить конкурс и вернуть модерацию\n\n"
     "<b>Приветствия новичкам:</b> включаются в «Настройки» чата — "
     "можно поменять текст или вернуть стандартный.\n\n"
     "Прочие команды:\n"
     "<code>/unmmute</code> <code>/unbban</code> <code>/rules</code>\n"
     "<code>/addrule</code> <code>/delrule</code>"
)


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Правила", callback_data="menu:rules")
    b.button(text="Добавить чат", callback_data="menu:addchat")
    b.button(text="Добавить правило", callback_data="menu:addrule")
    b.button(text="Настройки", callback_data="menu:settings")
    b.button(text="Удалить чат", callback_data="menu:delchat")
    b.adjust(2)
    return b.as_markup()


def chat_list_keyboard(chats: list[dict], action: str, back: str = "back:menu") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in chats:
        title = (c.get("title") or f"чат {c.get('chat_id')}")[:40]
        mark = "• " if c.get("enabled") else ""
        b.button(text=f"{mark}{title}", callback_data=f"{action}:{c['chat_id']}")
    b.button(text="Назад", callback_data=back)
    b.adjust(1)
    return b.as_markup()


def rules_keyboard(rules: list[dict], chat_id: int, enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rules:
        from .rules import Rule

        rule = Rule.from_dict(r)
        b.button(
            text=f"{r['id']} · {rule.to_display()}",
            callback_data=f"delrule:{r['id']}",
        )
    b.button(text="Добавить правило", callback_data=f"addrule2:{chat_id}")
    b.button(
        text="Включить" if not enabled else "На паузе",
        callback_data=f"togglechat:{chat_id}",
    )
    b.button(text="Настройки", callback_data=f"settings:{chat_id}")
    b.button(text="Назад", callback_data="menu:rules")
    b.adjust(1)
    return b.as_markup()


def settings_text(s: dict, chat: dict | None) -> str:
    title = esc((chat and chat.get("title")) or s["chat_id"])
    on = lambda v: "вкл" if v else "выкл"  # noqa: E731
    ai_warn = ""
    if int(s["ai_mode"]) == 1:
        from . import aimod

        if not aimod.is_configured():
            ai_warn = (
                "\nДля умного режима нужны AI_API_URL и AI_API_KEY в .env — пока он не работает."
            )
    greeting_preview = ""
    if int(s.get("greeting_enabled", 0)):
        tmpl = s.get("greeting_text") or DEFAULT_GREETING
        preview = " ".join(tmpl.split())
        if len(preview) > 70:
            preview = preview[:70] + "…"
        greeting_preview = f"\n<b>Текст:</b> «{esc(preview)}»"

    return (
        f"<b>Настройки чата</b> «{title}»\n\n"
        f"<b>Удалять нарушение:</b> {on(s['delete_on_violation'])}\n"
        f"<b>Уведомлять в чате:</b> {on(s['notify_group'])}\n"
        f"<b>Наказывать админов:</b> {on(s['punish_admins'])}\n\n"
        f"<b>Лимит предупреждений:</b> {s['warn_limit']}\n"
        f"После лимита — бан навсегда.\n\n"
        f"<b>Флуд:</b> {s['flood_messages']} сообщений за {s['flood_seconds']} сек\n"
        f"<b>Спам:</b> {s['spam_messages']} повторов за {s['spam_seconds']} сек\n\n"
        f"<b>Умная модерация:</b> {on(s['ai_mode'])}\n"
        f"<b>AI-проверка не чаще:</b> {s['ai_cooldown']} сек на пользователя"
        f"{ai_warn}\n\n"
        f"<b>Приветствия новичкам:</b> {on(s.get('greeting_enabled', 0))}"
        f"{greeting_preview}\n\n"
        "Чтобы задать точное число — нажми кнопку с числом и введи значение."
    )


def settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    cid = s["chat_id"]
    b = InlineKeyboardBuilder()
    b.button(
        text=f"Удалять нарушение: {'вкл' if s['delete_on_violation'] else 'выкл'}",
        callback_data=f"set:{cid}:delete_on_violation:{1 - s['delete_on_violation']}",
    )
    b.button(
        text=f"Уведомлять в чате: {'вкл' if s['notify_group'] else 'выкл'}",
        callback_data=f"set:{cid}:notify_group:{1 - s['notify_group']}",
    )
    b.button(
        text=f"Наказывать админов: {'вкл' if s['punish_admins'] else 'выкл'}",
        callback_data=f"set:{cid}:punish_admins:{1 - s['punish_admins']}",
    )

    _num_row(b, cid, "warn_limit", "Лимит предупреждений", s["warn_limit"], 1, 1, 999)
    _num_row(b, cid, "flood_messages", "Флуд, сообщений", s["flood_messages"], 1, 1, 100)
    _num_row(b, cid, "flood_seconds", "Флуд, окно сек", s["flood_seconds"], 5, 1, 3600)
    _num_row(b, cid, "spam_messages", "Спам, повторов", s["spam_messages"], 1, 1, 50)
    _num_row(b, cid, "spam_seconds", "Спам, окно сек", s["spam_seconds"], 5, 1, 3600)

    b.button(
        text=f"Умная модерация: {'вкл' if s['ai_mode'] else 'выкл'}",
        callback_data=f"set:{cid}:ai_mode:{1 - s['ai_mode']}",
    )
    _num_row(b, cid, "ai_cooldown", "AI-проверка, сек", s["ai_cooldown"], 5, 1, 3600)

    b.button(
        text=f"Приветствия новичкам: {'вкл' if s['greeting_enabled'] else 'выкл'}",
        callback_data=f"set:{cid}:greeting_enabled:{1 - s['greeting_enabled']}",
    )
    if s["greeting_enabled"]:
        b.button(text="Изменить приветствие", callback_data=f"greeting:{cid}")
        b.button(text="Сбросить (стандарт)", callback_data=f"greetingres:{cid}")

    b.button(text="В меню", callback_data="back:menu")
    b.adjust(1)
    return b.as_markup()


def _num_row(b: InlineKeyboardBuilder, cid: int, key: str, label: str,
             value: int, step: int, lo: int, hi: int) -> None:
    b.button(text=f"- {label}", callback_data=f"set:{cid}:{key}:{max(lo, value - step)}")
    b.button(text=f"{value}", callback_data=f"setin:{cid}:{key}")
    b.button(text=f"+ {label}", callback_data=f"set:{cid}:{key}:{min(hi, value + step)}")
