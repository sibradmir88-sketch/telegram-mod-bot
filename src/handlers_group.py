"""Модерация в группах и события добавления бота в чат."""

import time

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, ChatPermissions, Message

from .config import ADMIN_IDS
from .moderation import Trackers, apply_punishment, is_protected
from .rules import Rule, format_duration, parse_duration, parse_rule, rule_matches_text_dict
from .storage import Storage

router = Router()

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


async def notify_admins(bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


# ---------------------------------------------------------------- bot added/removed

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot, storage: Storage):
    chat = event.chat
    if chat.type not in GROUP_TYPES:
        return
    await storage.upsert_chat(chat.id, chat.title or "", chat.username or "")
    status = event.new_chat_member.status
    if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED):
        await notify_admins(
            bot,
            f"🤖 Меня добавили в чат «{chat.title or chat.id}».\n"
            "Назначь меня администратором и добавь чат: /start → ➕ Добавить чат",
        )
    elif status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        await notify_admins(bot, f"👋 Меня удалили из чата «{chat.title or chat.id}»")


# ---------------------------------------------------------------- admin commands in group

def _is_admin(user) -> bool:
    from .handlers_private import is_admin

    return is_admin(user)


async def _reply_target(message: Message) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


@router.message(Command("mute"), F.chat.type.in_(GROUP_TYPES))
async def group_mute(message: Message, bot, storage: Storage):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение нарушителя: /mute <длительность>")
        return
    duration = parse_duration(message.text) or 3600
    await bot.restrict_chat_member(
        message.chat.id, target,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=int(time.time()) + duration,
    )
    await message.answer(f"🔇 {message.reply_to_message.from_user.full_name} — мут {format_duration(duration)}")


@router.message(Command("ban"), F.chat.type.in_(GROUP_TYPES))
async def group_ban(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение нарушителя: /ban")
        return
    duration = parse_duration(message.text)
    until = int(time.time()) + duration if duration else None
    await bot.ban_chat_member(message.chat.id, target, until_date=until)
    await message.answer(f"⛔️ {message.reply_to_message.from_user.full_name} — бан {format_duration(duration)}")


@router.message(Command("kick"), F.chat.type.in_(GROUP_TYPES))
async def group_kick(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение нарушителя: /kick")
        return
    await bot.ban_chat_member(message.chat.id, target, revoke_messages=False)
    await bot.unban_chat_member(message.chat.id, target)
    await message.answer(f"👢 {message.reply_to_message.from_user.full_name} — кик")


@router.message(Command("warn"), F.chat.type.in_(GROUP_TYPES))
async def group_warn(message: Message, bot, storage: Storage):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение нарушителя: /warn")
        return
    settings = await storage.get_settings(message.chat.id)
    count = await storage.add_warning(message.chat.id, target)
    limit = int(settings.get("warn_limit", 3))
    text = f"⚠️ {message.reply_to_message.from_user.full_name} — варн {count}/{limit}"
    if count >= limit:
        await storage.reset_warnings(message.chat.id, target)
        mute_min = int(settings.get("warn_mute_min", 60))
        await bot.restrict_chat_member(
            message.chat.id, target,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + mute_min * 60,
        )
        text += f" → 🔇 мут {mute_min} мин"
    await message.answer(text)


@router.message(Command("unmute", "unrestrict"), F.chat.type.in_(GROUP_TYPES))
async def group_unmute(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение пользователя: /unmute")
        return
    await bot.restrict_chat_member(message.chat.id, target, permissions=ChatPermissions())
    await message.answer("✅ Мут снят")


@router.message(Command("unban"), F.chat.type.in_(GROUP_TYPES))
async def group_unban(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение пользователя: /unban")
        return
    await bot.unban_chat_member(message.chat.id, target)
    await message.answer("✅ Бан снят")


@router.message(Command("rules"), F.chat.type.in_(GROUP_TYPES))
async def group_rules(message: Message, storage: Storage):
    if not _is_admin(message.from_user):
        return
    rules = await storage.get_rules(message.chat.id)
    if not rules:
        await message.answer("Правил нет. Добавь: /addrule флуд - мут 1 час")
        return
    lines = [f"📜 Правила этого чата ({len(rules)}):", ""]
    for i, r in enumerate(rules, 1):
        rule = Rule.from_dict(r)
        lines.append(f"{i}. {rule.to_display()}")
    await message.answer("\n".join(lines))


@router.message(Command(commands=["rule", "addrule"]), F.chat.type.in_(GROUP_TYPES))
async def group_addrule(message: Message, storage: Storage):
    if not _is_admin(message.from_user):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer("Формат: /addrule нарушение - наказание\nНапример: /addrule флуд - мут 1 час")
        return
    rule, err = parse_rule(parts[1])
    if err:
        await message.answer("❌ " + err)
        return
    await storage.upsert_chat(message.chat.id, message.chat.title or "", message.chat.username or "")
    await storage.set_chat_enabled(message.chat.id, True)
    await storage.add_rule(message.chat.id, rule.trigger_type, rule.trigger_value, rule.action, rule.duration)
    await message.answer(f"✅ Правило добавлено в этот чат:\n{rule.to_display()}")


@router.message(Command("delrule"), F.chat.type.in_(GROUP_TYPES))
async def group_delrule(message: Message, storage: Storage):
    if not _is_admin(message.from_user):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: /delrule НОМЕР (номера смотри в /rules)")
        return
    idx = int(parts[1])
    rules = await storage.get_rules(message.chat.id)
    if idx < 1 or idx > len(rules):
        await message.answer("Не нашёл правило с таким номером")
        return
    await storage.delete_rule(rules[idx - 1]["id"])
    await message.answer("✅ Правило удалено")


# ---------------------------------------------------------------- auto moderation

async def handle_violation(bot, storage: Storage, message: Message, rule: dict, settings: dict):
    chat_id = message.chat.id
    user = message.from_user
    rule_obj = Rule.from_dict(rule)
    user_name = user.full_name or str(user.id)

    try:
        result = await apply_punishment(
            bot, storage, chat_id, user.id, rule_obj.action, rule_obj.duration, settings
        )
    except Exception as exc:  # бот не админ, пользователь уже недоступен и т.п.
        await notify_admins(
            bot,
            f"⚠️ Не смог наказать «{user_name}» (id {user.id}) в чате {chat_id}.\n"
            f"Правило: {rule_obj.to_display()}\nОшибка: {exc}\n\n"
            "Проверь, что бот админ в этом чате.",
        )
        return

    if settings.get("delete_on_violation"):
        try:
            await message.delete()
        except Exception:
            pass

    if settings.get("notify_group"):
        try:
            await message.answer(f"⚠️ {user_name} — {rule_obj.label} → {result}")
        except Exception:
            pass

    await notify_admins(
        bot,
        f"⚠️ <b>Нарушение</b>\n"
        f"Чат: {message.chat.title or chat_id}\n"
        f"Пользователь: <a href=\"tg://user?id={user.id}\">{user_name}</a>\n"
        f"Правило: {rule_obj.to_display()}\n"
        f"Действие: {result}",
    )


@router.message(F.chat.type.in_(GROUP_TYPES))
async def on_group_message(message: Message, bot, storage: Storage, trackers: Trackers):
    if not message.from_user or message.from_user.is_bot:
        return
    chat_id = message.chat.id

    chat = await storage.get_chat(chat_id)
    if not chat or not chat.get("enabled"):
        return
    await storage.upsert_chat(chat_id, message.chat.title or "", message.chat.username or "")

    user = message.from_user
    settings = await storage.get_settings(chat_id)
    rules = await storage.get_rules(chat_id)
    if not rules:
        return

    if not settings.get("punish_admins"):
        if await is_protected(bot, chat_id, user.id):
            return

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    by_type: dict[str, dict] = {}
    for r in rules:
        by_type.setdefault(r["trigger_type"], r)

    # повтор сообщений
    if "spam" in by_type:
        if trackers.check_spam(
            chat_id, user.id, text,
            int(settings.get("spam_messages", 3)), int(settings.get("spam_seconds", 20)),
        ):
            await handle_violation(bot, storage, message, by_type["spam"], settings)
            return

    # флуд
    if "flood" in by_type:
        if trackers.check_flood(
            chat_id, user.id,
            int(settings.get("flood_messages", 5)), int(settings.get("flood_seconds", 10)),
        ):
            await handle_violation(bot, storage, message, by_type["flood"], settings)
            return

    # текстовые правила: слово / ссылки / мат
    for r in rules:
        if r["trigger_type"] in ("flood", "spam"):
            continue
        if rule_matches_text_dict(r, text):
            await handle_violation(bot, storage, message, r, settings)
            return
