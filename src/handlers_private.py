"""Личные сообщения: только для админа, все остальные игнорируются."""

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .config import ADMIN_IDS, ADMIN_USERNAMES
from .rules import Rule, parse_rule
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
        "Используй меню 👇 или команды /start /help",
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
    status = "✅ активен" if enabled else "⏸ на паузе"

    lines = [f"📜 Правила чата «{title}»", ""]
    if rules:
        for i, r in enumerate(rules, 1):
            rule = Rule.from_dict(r)
            lines.append(f"{i}. {rule.to_display()}")
    else:
        lines.append("Правил пока нет — добавь первое правило!")
    lines += ["", f"Статус: {status}", "Кнопкой ✖️ удаляй лишние правила."]
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=rules_keyboard(rules, chat_id, enabled)
    )


async def show_addchat(callback: CallbackQuery, storage: Storage):
    chats = await storage.get_chats()
    if not chats:
        kb = chat_list_keyboard([], "enablechat")
        await callback.message.edit_text(
            "🤖 Пока нет чатов.\n\n"
            "1️⃣ Добавь меня в свой чат\n"
            "2️⃣ Назначь меня администратором\n"
            "3️⃣ Нажми «➕ Добавить чат» и выбери чат",
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
        "📜 Правила. Выбери чат:",
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
        "📝 Добавить правило. В какой чат?",
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
        "⚙️ Настройки. Выбери чат:",
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
        "❌ Удалить чат (вместе с правилами). Выбери чат:",
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
    await callback.answer("Чат подключён ✅")
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
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delconfirm:{chat_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="menu:delchat"),
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
        "📝 Отправь правило в формате:\n\n"
        "<b>нарушение - наказание</b>\n\n"
        "Примеры:\n"
        "• <code>флуд - мут 1 час</code>\n"
        "• <code>реклама - бан</code>\n"
        "• <code>мат - мут 30 минут</code>\n"
        "• <code>слово:айпи - кик</code>\n"
        "• <code>спам - мут 2 часа</code>\n\n"
        "Наказания: 🔇 мут, ⛔️ бан, 👢 кик, ⚠️ варн.\n"
        "Длительность: 30 минут, 2 часа, 1 день, навсегда.",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddRule.waiting_text, F.chat.type == ChatType.PRIVATE)
async def on_rule_text(message: Message, state: FSMContext, storage: Storage):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    chat_id = int(data.get("chat_id", 0))
    rule, err = parse_rule(message.text or "")
    if err:
        await message.answer(f"❌ {err}")
        return
    await storage.add_rule(
        chat_id, rule.trigger_type, rule.trigger_value, rule.action, rule.duration
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📜 К правилам", callback_data=f"rules:{chat_id}"),
                InlineKeyboardButton(text="🔙 В меню", callback_data="back:menu"),
            ]
        ]
    )
    await message.answer(
        f"✅ Правило добавлено!\n\n{rule.to_display()}\n\n"
        "Отправь следующее правило или вернись в меню.",
        reply_markup=kb,
    )


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
    await callback.answer("Правило удалено ✅")
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
    await callback.answer("Сохранено ✅")
    s = await storage.get_settings(chat_id)
    chat = await storage.get_chat(chat_id)
    await callback.message.edit_text(
        settings_text(s, chat), reply_markup=settings_keyboard(s)
    )
