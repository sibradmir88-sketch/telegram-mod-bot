"""Личные сообщения: только для админа, все остальные игнорируются."""

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .config import ADMIN_IDS, ADMIN_USERNAMES
from .rules import Rule, parse_rules_bulk
from .storage import Storage
from .ui import (
    HELP_TEXT,
    WELCOME_TEXT,
    chat_list_keyboard,
    esc,
    main_menu,
    rules_keyboard,
    settings_keyboard,
    settings_text,
)

router = Router()


class AddRule(StatesGroup):
    waiting_text = State()


class EditNumber(StatesGroup):
    waiting = State()


class GreetingText(StatesGroup):
    waiting = State()


NUMERIC_KEYS = {
    "warn_limit": "лимит предупреждений",
    "flood_messages": "флуд — количество сообщений",
    "flood_seconds": "флуд — окно (секунд)",
    "spam_messages": "спам — количество повторов",
    "spam_seconds": "спам — окно (секунд)",
    "ai_cooldown": "AI-проверка — не чаще, раз в секунд",
}


def is_admin(user) -> bool:
    if not user:
        return False
    if user.id in ADMIN_IDS:
        return True
    if user.username and user.username.lower() in ADMIN_USERNAMES:
        return True
    return False


# ---------------------------------------------------------------- start / help

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message):
    if not is_admin(message.from_user):
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu(), disable_web_page_preview=True)


@router.message(Command("help"), F.chat.type == ChatType.PRIVATE)
async def cmd_help(message: Message):
    if not is_admin(message.from_user):
        return
    await message.answer(HELP_TEXT, disable_web_page_preview=True)


@router.message(StateFilter(None), F.chat.type == ChatType.PRIVATE)
async def on_private_other(message: Message):
    if not is_admin(message.from_user):
        return
    await message.answer(
        "Используй меню или команды /start /help",
        reply_markup=main_menu(),
    )


# ---------------------------------------------------------------- menu

async def edit_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        WELCOME_TEXT, reply_markup=main_menu(), disable_web_page_preview=True
    )


async def show_rules_view(callback: CallbackQuery, chat_id: int, storage: Storage):
    chat = await storage.get_chat(chat_id)
    rules = await storage.get_rules(chat_id)
    title = esc((chat and chat.get("title")) or f"чат {chat_id}")
    enabled = bool(chat and chat.get("enabled"))
    status = "активен" if enabled else "на паузе"

    lines = [f"<b>Правила чата</b> «{title}»", ""]
    if rules:
        for i, r in enumerate(rules, 1):
            rule = Rule.from_dict(r)
            lines.append(f"{i}. {rule.to_display()}")
        if any(r["trigger_type"] == "ai" for r in rules):
            from . import aimod

            if not aimod.is_configured():
                lines += ["", "Нейро-правила требуют AI_API_URL/AI_API_KEY в .env."]
    else:
        lines.append("Правил пока нет — добавь первое правило!")
    lines += ["", f"Статус: {status}", "Кнопкой с номером удаляй лишние правила."]
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=rules_keyboard(rules, chat_id, enabled)
    )


async def show_addchat(callback: CallbackQuery, storage: Storage):
    chats = await storage.get_chats()
    if not chats:
        kb = chat_list_keyboard([], "enablechat")
        await callback.message.edit_text(
            "Пока нет чатов.\n\n"
            "1. Добавь меня в свой чат\n"
            "2. Назначь меня администратором\n"
            "3. Нажми «Добавить чат» и выбери чат",
            reply_markup=kb,
        )
        return
    await callback.message.edit_text(
        "Выбери чат, за которым следить:",
        reply_markup=chat_list_keyboard(chats, "enablechat"),
    )


@router.callback_query(F.data == "menu:rules")
async def cb_menu_rules(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chats = await storage.get_chats()
    if not chats:
        await show_addchat(callback, storage)
        return
    await callback.message.edit_text(
        "Правила. Выбери чат:",
        reply_markup=chat_list_keyboard(chats, "rules"),
    )


@router.callback_query(F.data == "menu:addchat")
async def cb_menu_addchat(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    await show_addchat(callback, storage)


@router.callback_query(F.data == "menu:addrule")
async def cb_menu_addrule(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chats = await storage.get_chats()
    if not chats:
        await show_addchat(callback, storage)
        return
    await callback.message.edit_text(
        "Добавить правило. В какой чат?",
        reply_markup=chat_list_keyboard(chats, "addrule2"),
    )


@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chats = await storage.get_chats()
    if not chats:
        await show_addchat(callback, storage)
        return
    await callback.message.edit_text(
        "Настройки. Выбери чат:",
        reply_markup=chat_list_keyboard(chats, "settings"),
    )


@router.callback_query(F.data == "menu:delchat")
async def cb_menu_delchat(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chats = await storage.get_chats()
    if not chats:
        await show_addchat(callback, storage)
        return
    await callback.message.edit_text(
        "Удалить чат (вместе с правилами). Выбери чат:",
        reply_markup=chat_list_keyboard(chats, "delchat"),
    )


@router.callback_query(F.data == "back:menu")
async def cb_back(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    await edit_menu(callback)


# ---------------------------------------------------------------- rules by chat

@router.callback_query(F.data.startswith("rules:"))
async def cb_rules(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await show_rules_view(callback, chat_id, storage)


@router.callback_query(F.data.startswith("enablechat:"))
async def cb_enablechat(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await storage.set_chat_enabled(chat_id, True)
    await callback.answer("Чат подключён")
    await show_rules_view(callback, chat_id, storage)


@router.callback_query(F.data.startswith("togglechat:"))
async def cb_togglechat(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    chat = await storage.get_chat(chat_id)
    if chat:
        await storage.set_chat_enabled(chat_id, not bool(chat.get("enabled")))
    await show_rules_view(callback, chat_id, storage)


@router.callback_query(F.data.startswith("delchat:"))
async def cb_delchat(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data=f"delconfirm:{chat_id}"),
                InlineKeyboardButton(text="Отмена", callback_data="menu:delchat"),
            ]
        ]
    )
    await callback.message.edit_text(
        f"Точно удалить чат {chat_id} вместе со всеми правилами?", reply_markup=kb
    )


@router.callback_query(F.data.startswith("delconfirm:"))
async def cb_delconfirm(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await storage.remove_chat(chat_id)
    await callback.answer("Чат удалён")
    await edit_menu(callback)


# ---------------------------------------------------------------- add rule wizard

@router.callback_query(F.data.startswith("addrule2:"))
async def cb_addrule2(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AddRule.waiting_text)
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        "<b>Отправь правило</b> в формате:\n\n"
        "<code>нарушение - наказание</code>\n\n"
        "• <b>Можно сразу целый блок</b> — по одному правилу на строку.\n\n"
        "<b>Примеры:</b>\n"
        "• <code>флуд - мут 1 час</code>\n"
        "• <code>реклама - бан</code>\n"
        "• <code>мат - мут 30 минут</code>\n"
        "• <code>слово:айпи - кик</code>\n"
        "• <code>спам - мут 2 часа</code>\n\n"
        "<b>Наказания:</b> мут, бан, кик, варн (предупреждение).\n"
        "<b>Длительность:</b> 30 минут, 2 часа, 1 день, навсегда.\n\n"
        "<b>Умный режим:</b> можно указать несколько вариантов через «/» —\n"
        "например <code>реклама - мут 1-2 часа / бан</code>. Тогда нейросеть "
        "сама выберет наказание по тяжести нарушения.",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddRule.waiting_text, F.chat.type == ChatType.PRIVATE)
async def on_rule_text(message: Message, state: FSMContext, storage: Storage):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    chat_id = int(data.get("chat_id", 0))
    rules, errors = parse_rules_bulk(message.text or "")

    if not rules:
        await message.answer(
            "Не нашёл ни одного правила.\n\n"
            "Формат: <code>нарушение - наказание</code>, по одному правилу на строку.\n"
            "Например: <code>флуд - мут 1 час</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К правилам", callback_data=f"rules:{chat_id}"),
                InlineKeyboardButton(text="В меню", callback_data="back:menu"),
            ]
        ]
    )

    for rule in rules:
        await storage.add_rule(
            chat_id, rule.trigger_type, rule.trigger_value, rule.action, rule.duration,
            rule.raw_text,
        )

    lines = [f"<b>Добавлено правил: {len(rules)}</b>", ""]
    for rule in rules:
        lines.append(f"• {rule.to_display()}")
    if errors:
        lines += ["", f"Пропущено: {len(errors)} строк", *errors[:3]]
    if any(r.trigger_type == "ai" for r in rules):
        from . import aimod

        if not aimod.is_configured():
            lines += ["", "Нейро-правила требуют AI_API_URL и AI_API_KEY в .env — пока не работают."]
    lines += ["", "Отправь ещё или вернись в меню."]
    await message.answer("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("delrule:"))
async def cb_delrule(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    rule_id = int(callback.data.split(":", 1)[1])
    rule_row = await storage.get_rule(rule_id)
    if not rule_row:
        await callback.answer("Правило не найдено")
        return
    chat_id = int(rule_row["chat_id"])
    await storage.delete_rule(rule_id)
    await callback.answer("Правило удалено")
    await show_rules_view(callback, chat_id, storage)


# ---------------------------------------------------------------- settings

@router.callback_query(F.data.startswith("settings:"))
async def cb_settings(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await callback.message.edit_text(
        settings_text(s, chat), reply_markup=settings_keyboard(s)
    )


@router.callback_query(F.data.startswith("set:"))
async def cb_set(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    _, chat_id, key, value = callback.data.split(":", 3)
    chat_id = int(chat_id)
    await storage.update_setting(chat_id, key, int(value))
    await callback.answer("Сохранено")
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await callback.message.edit_text(
        settings_text(s, chat), reply_markup=settings_keyboard(s)
    )


@router.callback_query(F.data.startswith("greeting:"))
async def cb_greeting(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await state.set_state(GreetingText.waiting)
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        "<b>Новое приветствие</b>\n\n"
        "Отправь текст приветствия. Доступны подстановки:\n"
        "<code>{name}</code> — имя пользователя\n"
        "<code>{chat}</code> — название чата\n"
        "<code>{username}</code> — @никнейм (если есть)\n\n"
        "Пример:\n<code>Привет, {name}! Добро пожаловать в {chat}!</code>\n\n"
        "Чтобы вернуть стандартное — в настройках нажми «Сбросить»."
    )


@router.message(GreetingText.waiting, F.chat.type == ChatType.PRIVATE)
async def on_greeting_text(message: Message, state: FSMContext, storage: Storage):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    chat_id = int(data.get("chat_id", 0))
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст приветствия не может быть пустым.")
        return
    await storage.set_greeting(chat_id, text)
    await state.clear()
    await message.answer(
        f"<b>Приветствие сохранено:</b>\n\n{esc(text)}", parse_mode=ParseMode.HTML
    )
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await message.answer(settings_text(s, chat), reply_markup=settings_keyboard(s))


@router.callback_query(F.data.startswith("greetingres:"))
async def cb_greeting_reset(callback: CallbackQuery, storage: Storage):
    if not is_admin(callback.from_user):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await storage.set_greeting(chat_id, "")
    await callback.answer("Стандартное приветствие восстановлено")
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await callback.message.edit_text(
        settings_text(s, chat), reply_markup=settings_keyboard(s)
    )


@router.callback_query(F.data.startswith("setin:"))
async def cb_setin(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    _, chat_id, key = callback.data.split(":", 2)
    chat_id = int(chat_id)
    label = NUMERIC_KEYS.get(key, key)
    await state.set_state(EditNumber.waiting)
    await state.update_data(chat_id=chat_id, key=key)
    await callback.message.edit_text(
        f"<b>Введи новое значение</b> для «{label}».\n\n"
        "Отправь целое число (от 1 до 99999).\n"
        "Например: <code>7</code> или <code>120</code>",
        parse_mode=ParseMode.HTML,
    )


@router.message(EditNumber.waiting, F.chat.type == ChatType.PRIVATE)
async def on_edit_number(message: Message, state: FSMContext, storage: Storage):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    chat_id = int(data.get("chat_id", 0))
    key = data.get("key", "")
    try:
        value = int((message.text or "").strip().replace(" ", ""))
    except ValueError:
        await message.answer("Это не число. Отправь целое число, например <code>10</code>.", parse_mode=ParseMode.HTML)
        return
    if value < 1 or value > 99999:
        await message.answer("Число должно быть от 1 до 99999.")
        return
    await storage.update_setting(chat_id, key, value)
    await state.clear()
    await message.answer(f"Сохранено: {NUMERIC_KEYS.get(key, key)} = <b>{value}</b>", parse_mode=ParseMode.HTML)
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await message.answer(settings_text(s, chat), reply_markup=settings_keyboard(s))
