"""Разбор и форматирование правил: «нарушение - наказание»."""

import re
from dataclasses import dataclass
from html import escape as _esc

ACTIONS = {
    "mute": "мут",
    "ban": "бан",
    "kick": "кик",
    "warn": "варн",
}
SEVERITY = {"warn": 1, "kick": 2, "mute": 3, "ban": 4}

TRIGGER_LABELS = {
    "flood": "🌊 флуд",
    "links": "🔗 ссылки/реклама",
    "mat": "🤬 мат",
    "spam": "🔁 повтор/спам",
    "word": "💬 слово",
}


@dataclass
class Rule:
    id: int
    chat_id: int
    trigger_type: str
    trigger_value: str | None
    action: str
    duration: int | None  # секунды или None = навсегда
    created_at: int

    @property
    def label(self) -> str:
        if self.trigger_type == "word" and self.trigger_value:
            return f"💬 «{_esc(self.trigger_value)}»"
        return TRIGGER_LABELS.get(self.trigger_type, self.trigger_type)

    @property
    def action_label(self) -> str:
        act = ACTIONS.get(self.action, self.action)
        if self.duration is not None and self.action in ("mute", "ban"):
            return f"{act} {format_duration(self.duration)}"
        return act

    def to_display(self) -> str:
        return f"{self.label} → {self.action_label}"

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            id=int(d.get("id") or 0),
            chat_id=int(d.get("chat_id") or 0),
            trigger_type=str(d.get("trigger_type") or ""),
            trigger_value=d.get("trigger_value"),
            action=str(d.get("action") or ""),
            duration=d.get("duration"),
            created_at=int(d.get("created_at") or 0),
        )


# ---------------------------------------------------------------- duration

_UNITS = [
    (("год", "года", "года", "лет", "годов", "г"), 31536000),
    (("месяц", "месяца", "месяцев", "мес"), 2592000),
    (("неделю", "неделя", "недели", "недель", "нед"), 604800),
    (("день", "дня", "дней", "суток", "сутки", "д"), 86400),
    (("час", "часа", "часов", "ч"), 3600),
    (("минуту", "минута", "минуты", "минут", "мин", "м"), 60),
    (("секунду", "секунда", "секунды", "секунд", "сек", "с"), 1),
]

_DURATION_RE = re.compile(r"(\d+)\s*([а-яёa-z]+)", re.I)


def parse_duration(text: str) -> int | None:
    """Возвращает длительность в секундах или None = навсегда."""
    if not text:
        return None
    t = text.strip().lower()
    if any(w in t for w in ("навсегда", "перманент", "бессрочн", "навечно", "вечно", "forever", "permanent")):
        return None
    m = _DURATION_RE.search(t)
    if not m:
        return None
    num = int(m.group(1))
    word = m.group(2).lower()
    for names, seconds in _UNITS:
        if word in names:
            return num * seconds
    return None


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "навсегда"
    units = [
        (31536000, "год", "года", "лет"),
        (2592000, "месяц", "месяца", "месяцев"),
        (604800, "неделя", "недели", "недель"),
        (86400, "день", "дня", "дней"),
        (3600, "час", "часа", "часов"),
        (60, "минута", "минуты", "минут"),
        (1, "секунда", "секунды", "секунд"),
    ]
    for size, one, few, many in units:
        if seconds >= size:
            n = seconds // size
            return f"{n} {_plural(n, one, few, many)}"
    return f"{seconds} сек"


# ---------------------------------------------------------------- parsing

def parse_rule(raw: str) -> tuple[Rule | None, str | None]:
    """Возвращает (Rule, None) при успехе либо (None, ошибка)."""
    text = (
        raw.strip()
        .replace("—", "-")
        .replace("–", "-")
        .replace("→", "-")
        .replace("=>", "-")
    )
    if "-" not in text:
        return None, (
            "Не нашёл разделитель «-».\n\n"
            "Формат: нарушение - наказание\n"
            "Например: флуд - мут 1 час"
        )
    left, right = text.split("-", 1)
    left = left.strip().lower()
    right = right.strip().lower()
    if not left or not right:
        return None, "Пустое нарушение или наказание. Формат: нарушение - наказание"

    # --- что отслеживаем
    if left.startswith(("слово:", "word:", "слова:", "фраза:", "phrase:")):
        trigger_type, trigger_value = "word", left.split(":", 1)[1].strip()
    elif "флуд" in left or left == "flood":
        trigger_type, trigger_value = "flood", None
    elif any(k in left for k in ("ссылк", "линк", "реклам", "юзернейм", "username", "упоминание", "тег", "мёнт")):
        trigger_type, trigger_value = "links", None
    elif "мат" in left or "нецензур" in left or "матерщин" in left:
        trigger_type, trigger_value = "mat", None
    elif "повтор" in left or left in ("спам", "спам-сообщ"):
        trigger_type, trigger_value = "spam", None
    else:
        trigger_type, trigger_value = "word", left

    # --- что делаем
    if "мут" in right:
        action = "mute"
    elif "бан" in right:
        action = "ban"
    elif "кик" in right or "выгна" in right or "вылет" in right:
        action = "kick"
    elif "варн" in right or "предупрежд" in right or right.startswith("пред"):
        action = "warn"
    else:
        return None, (
            "Не понял наказание.\n\nИспользуй одно из: "
            "🔇 мут, ⛔️ бан, 👢 кик, ⚠️ варн (предупреждение)."
        )

    duration = parse_duration(right)
    if action == "mute" and duration is None and not any(
        w in right for w in ("навсегда", "перманент", "бессрочн", "forever", "permanent", "вечно")
    ):
        duration = 3600  # мут без длительности = 1 час
    if action == "warn":
        duration = None

    rule = Rule(
        id=0,
        chat_id=0,
        trigger_type=trigger_type,
        trigger_value=trigger_value,
        action=action,
        duration=duration,
        created_at=0,
    )
    return rule, None


# ---------------------------------------------------------------- matching

_URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|@[a-zA-Z0-9_]{4,})", re.I)

from .profanity import contains_profanity  # noqa: E402


def rule_matches_text(rule: Rule, text: str) -> bool:
    """Проверка текстовых правил (word / links / mat)."""
    if rule.trigger_type == "word":
        return bool(rule.trigger_value) and rule.trigger_value.lower() in text.lower()
    if rule.trigger_type == "links":
        return bool(_URL_RE.search(text))
    if rule.trigger_type == "mat":
        return contains_profanity(text)
    return False


def rule_matches_text_dict(rule: dict, text: str) -> bool:
    return rule_matches_text(Rule.from_dict(rule), text)
