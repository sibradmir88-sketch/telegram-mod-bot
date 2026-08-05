"""Модерация в группах и события добавления бота в чат."""

import logging
import re
import time

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, ChatPermissions, Message

from . import aimod
from .config import ADMIN_IDS, NEWS_CHANNEL_THRESHOLD
from .detect import extract_mentions, extract_telegram_links, is_invite_link
from .moderation import Trackers, apply_punishment, is_protected
from .rules import (
    Rule,
    SEVERITY,
    parse_duration,
    parse_rules_bulk,
    rule_matches_text_dict,
)
from .storage import Storage
from .ui import DEFAULT_GREETING, esc, render_greeting

router = Router()
log = logging.getLogger("greet")

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}

_ai_last: dict[tuple[int, int], float] = {}
_ai_violated: set[tuple[int, int]] = set()


def _build_rules_context(rules: list[dict]) -> str:
    """Список правил для нейросети: номер + описание + наказание (с вариантами)."""
    lines = []
    for i, r in enumerate(rules, 1):
        lines.append(f"{i}. {Rule.from_dict(r).to_context()}")
    return "\n".join(lines)


async def _ai_verdict(chat_id: int, user_id: int, rules: list[dict], text: str,
                      settings: dict, extra: str = "") -> dict | None:
    """Умная проверка сообщения по всем правилам. None — кулдаун или сбой ИИ."""
    key = (chat_id, user_id)
    now = time.time()
    cooldown = max(0, int(settings.get("ai_cooldown", 20)))
    if cooldown and key in _ai_last and now - _ai_last[key] < cooldown:
        return None  # недавно проверяли — сработают обычные локальные правила
    verdict = await aimod.analyze_message(_build_rules_context(rules), text, extra)
    if verdict is None:
        return None  # ошибка ИИ/сеть — обычная логика подстрахует
    _ai_last[key] = time.time()
    if verdict["violated"]:
        _ai_violated.add(key)
    else:
        _ai_violated.discard(key)
    return verdict


async def _channel_members(bot, handle: str) -> int | None:
    """Число подписчиков публичного канала/чата @handle. None — проверить нельзя."""
    if is_invite_link(handle):
        return None
    try:
        return int(await bot.get_chat_member_count("@" + handle))
    except Exception:
        return None


# ---------------------------------------------------------------- конкурс/розыгрыш

# Пока идёт конкурс комментариев («44-му комментарию — мишка»), бот не трогает
# флуд, спам, капс и эмодзи. Когда набрано N комментариев — возвращается.
_rewards: dict[int, dict] = {}

_REWARD_RE = re.compile(r"(\d+)\s*(?:-й|-го|-ому|-им|-ый|-ой|-ая|-ое|-его|-му)?\s*комментари", re.I)
_REWARD_WORDS = (
    "мишк", "приз", "наград", "розыгрыш", "конкурс", "выигр", "подар",
    "получ", "бонус", "марафон", "счастлив", "лоторея", "разыгр", "плюшк",
)


def _detect_reward(text: str) -> int | None:
    """Возвращает целевое число комментариев, если текст — объявление конкурса."""
    m = _REWARD_RE.search(text)
    if not m:
        return None
    low = text.lower()
    if not any(w in low for w in _REWARD_WORDS):
        return None
    return int(m.group(1))


# ---------------------------------------------------------------- повторное наказание

# После наказания пользователя не сообщаем о нём снова N секунд — иначе при
# серии нарушений (флуд/спам) бот заваливает чат одинаковыми сообщениями.
_recent_punish: dict[tuple[int, int], float] = {}
_PUNISH_COOLDOWN = 45


async def notify_admins(bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
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
            f"Меня добавили в чат «{esc(chat.title or chat.id)}».\n"
            "Назначь меня администратором и добавь чат: /start — «Добавить чат»",
        )
    elif status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        await notify_admins(bot, f"Меня удалили из чата «{esc(chat.title or chat.id)}»")


# ---------------------------------------------------------------- приветствие новичков

_join_times: dict[int, list[float]] = {}


def _greet_flood_ok(chat_id: int) -> bool:
    """Не приветствуем, если в чат массово вливается народ (защита от спама)."""
    now = time.time()
    times = _join_times.setdefault(chat_id, [])
    times[:] = [t for t in times if now - t < 60]
    if len(times) >= 10:
        return False
    times.append(now)
    return True


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated, bot, storage: Storage):
    chat = event.chat
    log.info("chat_member update: chat=%s type=%s new=%s old=%s",
             chat.id, chat.type, event.new_chat_member.status, event.old_chat_member.status)
    if chat.type not in GROUP_TYPES:
        return
    new = event.new_chat_member
    old = event.old_chat_member
    if new.status not in (
        ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED
    ):
        return
    if old.status in (
        ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.RESTRICTED, ChatMemberStatus.CREATOR,
    ):
        return  # не вступление, а например повышение прав
    user = new.user
    if user is None or user.is_bot:
        return

    settings = await storage.get_settings(chat.id)
    log.info("new member %s in %s, greeting_enabled=%s", user.full_name, chat.id,
             settings.get("greeting_enabled"))
    if not int(settings.get("greeting_enabled", 0)):
        return
    if not _greet_flood_ok(chat.id):
        return

    template = settings.get("greeting_text") or DEFAULT_GREETING
    name = user.full_name or user.first_name or str(user.id)
    username = f"@{user.username}" if user.username else ""
    text = esc(render_greeting(template, name, username, chat.title or ""))
    try:
        await bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
        log.info("greeting sent to %s in %s", user.full_name, chat.id)
    except Exception as exc:
        log.warning("greeting send failed: %s", exc)


# ---------------------------------------------------------------- admin commands in group

def _is_admin(user) -> bool:
    from .handlers_private import is_admin

    return is_admin(user)


async def _reply_target(message: Message) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


_DURATION_TOKEN_RE = re.compile(r"(\d+\s*[а-яёa-z]+)")
_FOREVER_WORDS = ("навсегда", "навечно", "вечно", "бессрочно", "перманентно", "forever", "permanent")


def _split_duration_reason(text: str) -> tuple[int | None, str]:
    """Отделяет длительность («2 часа», «навсегда») от причины.

    Возвращает (секунды или None, причина). None — значит «навсегда» или без срока.
    """
    t = text.strip().lstrip("-–—").strip()
    if not t:
        return None, ""
    first = t.split()[0].lower()
    if first in _FOREVER_WORDS:
        return None, " ".join(t.split()[1:]).strip(" .,;:–—")
    m = _DURATION_TOKEN_RE.search(t)
    if m and m.start() == 0:
        seconds = parse_duration(m.group(0))
        if seconds is not None:
            return seconds, t[m.end():].strip(" .,;:–—")
    return None, t


def _punish_title(action: str, result: str) -> str:
    if action == "mute":
        return "Пользователь замучен"
    if action == "ban":
        return "Пользователь заблокирован"
    if action == "kick":
        return "Пользователь исключён"
    if "бан" in result:
        return "Пользователь заблокирован навсегда"
    return "Пользователь получил предупреждение"


_MOD_ACTIONS = {
    "bban": "ban", "ban": "ban",
    "mmute": "mute", "mute": "mute",
    "kkick": "kick", "kick": "kick",
    "wwarn": "warn", "warn": "warn",
}


@router.message(F.chat.type.in_(GROUP_TYPES), Command(*_MOD_ACTIONS))
async def group_mod_command(message: Message, bot, storage: Storage):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer(
            "Ответь на сообщение нарушителя и укажи наказание:\n\n"
            "<code>/bban время причина</code> — бан\n"
            "<code>/mmute время причина</code> — мут\n"
            "<code>/kkick причина</code> — кик\n"
            "<code>/wwarn время причина</code> — предупреждение",
            parse_mode=ParseMode.HTML,
        )
        return

    parts = message.text.split()
    cmd = parts[0].lstrip("/").lower()
    action = _MOD_ACTIONS[cmd]
    duration, reason = _split_duration_reason(" ".join(parts[1:]))
    if action == "mute" and duration is None:
        duration = 3600  # мут без срока = 1 час

    target_user = message.reply_to_message.from_user
    user_name = target_user.full_name or str(target_user.id)
    settings = await storage.get_settings(message.chat.id)

    try:
        result = await apply_punishment(
            bot, storage, message.chat.id, target, action, duration, settings,
            expiry=int(time.time()) + duration if (action == "warn" and duration) else None,
        )
    except Exception as exc:
        await notify_admins(
            bot,
            f"Не смог наказать «{esc(user_name)}» (id {target}) в чате {message.chat.id}.\n"
            f"Команда: {cmd}. Ошибка: {esc(str(exc))}\n\n"
            "Проверь, что бот админ в этом чате.",
        )
        return

    lines = [
        f"<b>{_punish_title(action, result)}</b>",
        "",
        f"<b>Пользователь:</b> <a href=\"tg://user?id={target}\">{esc(user_name)}</a>",
        f"<b>Наказание:</b> {result}",
    ]
    if reason:
        lines.append(f"<b>Причина:</b> {esc(reason)}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    await notify_admins(
        bot,
        f"<b>{_punish_title(action, result)}</b>\n"
        f"Чат: {esc(message.chat.title or message.chat.id)}\n"
        f"Пользователь: <a href=\"tg://user?id={target}\">{esc(user_name)}</a>\n"
        f"Наказание: {result}"
        + (f"\nПричина: {esc(reason)}" if reason else ""),
    )


@router.message(Command("unmute", "unrestrict"), F.chat.type.in_(GROUP_TYPES))
async def group_unmute(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение пользователя: /unmute")
        return
    await bot.restrict_chat_member(message.chat.id, target, permissions=ChatPermissions())
    await message.answer("Мут снят")


@router.message(Command("unban"), F.chat.type.in_(GROUP_TYPES))
async def group_unban(message: Message, bot):
    if not _is_admin(message.from_user):
        return
    target = await _reply_target(message)
    if not target:
        await message.answer("Ответь на сообщение пользователя: /unban")
        return
    await bot.unban_chat_member(message.chat.id, target)
    await message.answer("Бан снят")


@router.message(Command("rules"), F.chat.type.in_(GROUP_TYPES))
async def group_rules(message: Message, storage: Storage):
    if not _is_admin(message.from_user):
        return
    rules = await storage.get_rules(message.chat.id)
    if not rules:
        await message.answer("Правил нет. Добавь: /addrule флуд - мут 1 час")
        return
    lines = [f"<b>Правила этого чата</b> ({len(rules)}):", ""]
    for i, r in enumerate(rules, 1):
        rule = Rule.from_dict(r)
        lines.append(f"{i}. {rule.to_display()}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command(commands=["rule", "addrule"]), F.chat.type.in_(GROUP_TYPES))
async def group_addrule(message: Message, storage: Storage):
    if not _is_admin(message.from_user):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer(
            "Формат: <code>/addrule нарушение - наказание</code>\n"
            "Например: <code>/addrule флуд - мут 1 час</code>\n\n"
            "Можно несколько правил — каждое с новой строки.",
            parse_mode=ParseMode.HTML,
        )
        return
    rules, errors = parse_rules_bulk(parts[1])
    if not rules:
        await message.answer("Не получилось разобрать.\n\n" + "\n".join(errors[:5]))
        return
    await storage.upsert_chat(message.chat.id, message.chat.title or "", message.chat.username or "")
    await storage.set_chat_enabled(message.chat.id, True)
    for rule in rules:
        await storage.add_rule(
            message.chat.id, rule.trigger_type, rule.trigger_value, rule.action, rule.duration,
            rule.raw_text,
        )
    lines = [f"Добавлено правил: {len(rules)}", ""]
    for rule in rules:
        lines.append(f"• {rule.to_display()}")
    if errors:
        lines += ["", f"Пропущено: {len(errors)}"]
    await message.answer("\n".join(lines))


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
    await message.answer("Правило удалено")


# ---------------------------------------------------------------- auto moderation

async def handle_violation(bot, storage: Storage, message: Message, rule: dict, settings: dict,
                           reason: str = "", rule_label: str | None = None):
    chat_id = message.chat.id
    user = message.from_user
    rule_obj = Rule.from_dict(rule)
    user_name = user.full_name or str(user.id)
    label = rule_label or rule_obj.label
    reason_line = f"\n<b>Причина:</b> {esc(reason)}" if reason else ""

    # уже наказали этого пользователя только что — не дублируем сообщения
    now = time.time()
    key = (chat_id, user.id)
    if now - _recent_punish.get(key, 0.0) < _PUNISH_COOLDOWN:
        if settings.get("delete_on_violation"):
            try:
                await message.delete()
            except Exception:
                pass
        return
    _recent_punish[key] = now

    try:
        result = await apply_punishment(
            bot, storage, chat_id, user.id, rule_obj.action, rule_obj.duration, settings
        )
    except Exception as exc:  # бот не админ, пользователь уже недоступен и т.п.
        await notify_admins(
            bot,
            f"Не смог наказать «{esc(user_name)}» (id {user.id}) в чате {chat_id}.\n"
            f"Правило: {label}\nОшибка: {esc(str(exc))}\n\n"
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
            await message.answer(
                f"<b>{_punish_title(rule_obj.action, result)}</b>\n"
                f"<b>Пользователь:</b> <a href=\"tg://user?id={user.id}\">{esc(user_name)}</a>\n"
                f"<b>Нарушено:</b> {esc(label)}\n"
                f"<b>Наказание:</b> {result}{reason_line}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    await notify_admins(
        bot,
        f"<b>Нарушение правил</b>\n"
        f"Чат: {esc(message.chat.title or chat_id)}\n"
        f"Пользователь: <a href=\"tg://user?id={user.id}\">{esc(user_name)}</a>\n"
        f"Нарушено: {esc(label)}\n"
        f"Наказание: {result}{reason_line}",
    )


# ---------------------------------------------------------------- конкурс/розыгрыш

@router.message(Command("reward"), F.chat.type.in_(GROUP_TYPES))
async def group_reward(message: Message):
    if not _is_admin(message.from_user):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Формат: /reward ЧИСЛО\n"
            "До скольких комментариев длится конкурс, например: /reward 44"
        )
        return
    target = max(1, int(parts[1]))
    _rewards[message.chat.id] = {"target": target, "count": 0}
    await message.answer(
        f"<b>Конкурс начат</b>: до {target}-го комментария бот не трогает флуд и спам.\n"
        f"Как только наберётся {target} комментариев — модерация вернётся."
    )


@router.message(Command("rewardstop"), F.chat.type.in_(GROUP_TYPES))
async def group_rewardstop(message: Message):
    if not _is_admin(message.from_user):
        return
    if _rewards.pop(message.chat.id, None):
        await message.answer("Конкурс остановлен. Модерация вернулась.")
    else:
        await message.answer("Сейчас конкурс не идёт.")


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

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    by_type: dict[str, dict] = {}
    for r in rules:
        by_type.setdefault(r["trigger_type"], r)

    # --- конкурс комментариев: объявление «44-му комментарию — мишка» ---
    reward_target = _detect_reward(text)
    if reward_target:
        _rewards[chat_id] = {"target": reward_target, "count": 0}
        try:
            await message.answer(
                f"<b>Конкурс комментариев!</b>\n"
                f"До {reward_target}-го комментария бот не трогает флуд и спам.\n"
                f"Когда наберётся {reward_target} — модерация вернётся.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    reward = _rewards.get(chat_id)
    reward_active = bool(reward)
    if reward_active:
        reward["count"] += 1
        if reward["count"] >= reward["target"]:
            _rewards.pop(chat_id, None)
            try:
                await message.answer(
                    "Конкурс завершён — модерация вернулась в обычный режим.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return  # победный комментарий не наказываем

    if not settings.get("punish_admins"):
        if await is_protected(bot, chat_id, user.id):
            return

    # --- дополнительная информация для нейромодуля: ссылки, фото, пересылки ---
    extra_lines: list[str] = []
    handles = extract_telegram_links(text)
    mentions = extract_mentions(text)
    if message.photo:
        extra_lines.append("В сообщении есть фото.")
    elif message.video:
        extra_lines.append("В сообщении есть видео.")
    fo = message.forward_origin
    if fo is not None and getattr(fo, "type", None) == "channel":
        fchat = getattr(fo, "chat", None)
        if fchat is not None and getattr(fchat, "title", None):
            fu = getattr(fchat, "username", None)
            extra_lines.append(
                f"Сообщение переслано из канала «{esc(fchat.title)}»"
                f"{f' (@{fu})' if fu else ''}."
            )
            if fu and fu not in handles:
                handles.append(fu)
    link_info: dict[str, int | None] = {}
    if handles:
        for h in handles:
            link_info[h] = await _channel_members(bot, h)
        for h, cnt in link_info.items():
            if is_invite_link(h):
                extra_lines.append(f"Ссылка-приглашение на приватный чат: t.me/{h}.")
            elif cnt is None:
                extra_lines.append(f"Ссылка на @{h} — подписчиков не проверить.")
            else:
                extra_lines.append(f"Ссылка на @{h} — подписчиков: {cnt}.")
    for u in mentions:
        extra_lines.append(f"Упоминание @{u}.")

    # --- локальные детекторы: собираем ВСЕ совпавшие правила ---
    matched: list[dict] = []
    for r in rules:
        if r["trigger_type"] in ("spam", "flood", "ai"):
            continue
        if rule_matches_text_dict(r, text):
            matched.append(r)

    spam_hit = flood_hit = False
    if not reward_active:
        if "spam" in by_type and trackers.check_spam(
            chat_id, user.id, text,
            int(settings.get("spam_messages", 3)), int(settings.get("spam_seconds", 20)),
        ):
            spam_hit = True
        if "flood" in by_type and trackers.check_flood(
            chat_id, user.id,
            int(settings.get("flood_messages", 5)), int(settings.get("flood_seconds", 10)),
        ):
            flood_hit = True
    else:
        extra_lines.append(
            "В чате проходит конкурс комментариев — короткие повторяющиеся "
            "сообщения, капс и эмодзи не считаются нарушением."
        )

    # во время конкурса не трогаем лёгкие нарушения
    if reward_active:
        matched = [r for r in matched if r["trigger_type"] not in ("nonsense", "caps", "emoji")]

    if matched:
        extra_lines.append(
            "Локально определено нарушение: " + ", ".join(Rule.from_dict(r).label for r in matched) + "."
        )
    if spam_hit:
        extra_lines.append("Есть повтор сообщений (спам).")
    if flood_hit:
        extra_lines.append("Есть флуд.")
    extra = "\n".join(extra_lines) if extra_lines else ""

    # жёсткое правило: реклама чужого канала/чата по ссылке → бан.
    # Ссылки на новостные каналы (100 000+ подписчиков) — не нарушение.
    if "links" in by_type and handles:
        promo = [h for h, c in link_info.items()
                 if c is None or c < NEWS_CHANNEL_THRESHOLD]
        if not promo:
            return
        rule = dict(by_type["links"])
        rule["action"] = "ban"
        rule["duration"] = None
        await handle_violation(
            bot, storage, message, rule, settings,
            reason="реклама чужого канала/чата",
        )
        return

    # --- умная нейро-модерация: ИИ складывает ВСЕ нарушения в одно наказание ---
    # короткие междометия («f», «k», «да», «хз») без явного нарушения не наказываем
    letter_count = sum(1 for c in text if c.isalpha())
    if not matched and not spam_hit and not flood_hit and not handles and letter_count <= 2:
        return
    ai_on = int(settings.get("ai_mode", 0)) == 1
    if ai_on and aimod.is_configured():
        verdict = await _ai_verdict(chat_id, user.id, rules, text, settings, extra)
        if verdict is not None:
            if not verdict["violated"]:
                return
            if matched:
                label = ", ".join(Rule.from_dict(r).label for r in matched)
            elif isinstance(verdict.get("rule_index"), int):
                rule_idx = verdict["rule_index"]
                if 1 <= rule_idx <= len(rules):
                    label = Rule.from_dict(rules[rule_idx - 1]).label
                else:
                    label = verdict.get("reason") or "несколько нарушений"
            else:
                label = verdict.get("reason") or "несколько нарушений"
            action = verdict.get("action")
            dm = verdict.get("duration_minutes")
            duration = dm * 60 if dm is not None else None
            if action == "mute" and duration is None:
                duration = 3600
            rule = {
                "trigger_type": "ai",
                "trigger_value": label,
                "action": action or "warn",
                "duration": duration,
            }
            await handle_violation(
                bot, storage, message, rule, settings,
                reason=verdict.get("reason", ""),
                rule_label=label,
            )
            return

    # --- запасной путь без ИИ: повтор, флуд, самое строгое из совпадений ---
    if spam_hit:
        await handle_violation(bot, storage, message, by_type["spam"], settings)
        return
    if flood_hit:
        await handle_violation(bot, storage, message, by_type["flood"], settings)
        return
    if matched:
        strictest = max(matched, key=lambda r: SEVERITY.get(r.get("action"), 0))
        await handle_violation(bot, storage, message, strictest, settings)
        return

    # правила-ai: проверить по одному, если умный режим выключен
    for r in rules:
        if r["trigger_type"] != "ai":
            continue
        if ai_on or not aimod.is_configured():
            continue
        if await aimod.moderate(r.get("trigger_value") or "правила чата", text):
            await handle_violation(bot, storage, message, r, settings)
            return
