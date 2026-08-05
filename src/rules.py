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
    "flood": "Флуд",
    "spam": "Спам и повторы",
    "links": "Ссылки и реклама",
    "mat": "Мат",
    "insult": "Оскорбления и травля",
    "threat": "Угрозы и шантаж",
    "scam": "Мошенничество и обман",
    "nsfw": "Контент 18+",
    "pii": "Чужие данные",
    "caps": "Капс",
    "emoji": "Флуд эмодзи",
    "nonsense": "Бессмыслица",
    "ai": "Нейро-модерация",
    "word": "Слово",
}

# Семантические триггеры, которые лучше всего ловятся нейросетью
AI_TRIGGERS = {"ai"}

# Триггеры, обрабатываемые локальными детекторами из detect.py
LOCAL_TEXT_TRIGGERS = {
    "links", "mat", "insult", "threat", "scam", "nsfw", "pii", "caps", "emoji", "nonsense",
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
    raw_text: str | None = None

    @property
    def label(self) -> str:
        if self.trigger_type in ("word", "ai") and self.trigger_value:
            return f"«{_esc(self.trigger_value)}»"
        return TRIGGER_LABELS.get(self.trigger_type, self.trigger_type)

    @property
    def action_label(self) -> str:
        act = ACTIONS.get(self.action, self.action)
        if self.duration is not None and self.action in ("mute", "ban"):
            return f"{act} {format_duration(self.duration)}"
        return act

    def to_display(self) -> str:
        # Если в правиле несколько вариантов наказания («мут 1-6 часов / бан»)
        # — показываем их все, чтобы было видно, что выбирает нейросеть.
        if self.raw_text:
            _left, right = _split_left_right(self.raw_text)
            if right and ("/" in right or "(" in right):
                return f"{self.label} — {right.strip()[:140]}"
        return f"{self.label} — {self.action_label}"

    def to_context(self) -> str:
        """Строка правила для нейросети: описание + наказание с вариантами."""
        return self.raw_text or f"{self.label} — {self.action_label}"

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
            raw_text=d.get("raw_text"),
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

_BULLET_RE = re.compile(r"^[^А-Яа-яЁёA-Za-z0-9«\"]+")


def _split_left_right(text: str) -> tuple[str | None, str | None]:
    """Разделяет «нарушение ... наказание» по «Наказание:» или «-»."""
    m = re.search(r"наказание\s*[:»]?", text, re.I)
    if m:
        left = text[: m.start()]
        right = text[m.end():]
        return left, right
    if "-" in text:
        left, right = text.split("-", 1)
        return left, right
    return None, None


def _clean_left(left: str) -> str:
    left = left.strip()
    left = _BULLET_RE.sub("", left)
    return left.strip(" .,;:»«\"").strip()


def _detect_trigger(left: str) -> tuple[str, str | None]:
    """По тексту нарушения выбирает тип детектора."""
    l = left.lower()
    if l.startswith(("слово:", "word:", "слова:", "фраза:", "phrase:")):
        return "word", l.split(":", 1)[1].strip()
    if "флуд" in l or l == "flood":
        return "flood", None
    if "капс" in l or "заглавн" in l or "криком" in l:
        return "caps", None
    if any(k in l for k in ("эмодзи", "эмоджи", "смайл")):
        return "emoji", None
    if any(k in l for k in ("повтор", "однообразн", "дословно")):
        return "spam", None
    if any(k in l for k in ("ссылк", "линк", "реклам", "самопиар", "юзернейм",
                            "username", "упоминание", "мёнт")):
        return "links", None
    if re.search(r"(?<![а-яёa-z])мат(?![а-яёa-z])", l) or "нецензур" in l or "матерщин" in l or "бран" in l:
        return "mat", None
    if any(k in l for k in ("угроз", "шантаж", "запугиван")):
        return "threat", None
    if any(k in l for k in ("оскорб", "травл", "униж", "буллинг", "обид", "хам")):
        return "insult", None
    if any(k in l for k in ("мошен", "обман", "лохотрон", "афёр")):
        return "scam", None
    if any(k in l for k in ("18+", "контент 18", "порн", "шокирующ", "насил",
                            "жесток", "эрот")):
        return "nsfw", None
    if any(k in l for k in ("чужие данные", "личные данные", "персональн", "паспорт",
                            "банковск", "номер карт", "публикуйте")):
        return "pii", None
    if any(k in l for k in ("бессмыслен", "бессвязн", "мусор")):
        return "nonsense", None
    if any(k in l for k in ("ложную информац", "слух", "фейк", "ложные сведен")):
        return "ai", left
    if any(k in l for k in ("конфликт", "провоцир", "разжига", "ссор")):
        return "ai", left
    if "спам" in l:
        return "spam", None
    return "word", left


def parse_rule(raw: str) -> tuple[Rule | None, str | None]:
    """Возвращает (Rule, None) при успехе либо (None, ошибка)."""
    text = (
        raw.strip()
        .replace("—", "-")
        .replace("–", "-")
        .replace("→", "-")
        .replace("=>", "-")
    )
    left, right = _split_left_right(text)
    if left is None:
        # Нет разделителя «-»/«Наказание:» — это заголовок/оформление, а не правило.
        return None, None
    left = _clean_left(left).lower()
    right = (right or "").strip(" .,;:»«\"\n").lower()
    if not left or not right:
        return None, "Пустое нарушение или наказание. Формат: нарушение - наказание"

    # --- что отслеживаем
    trigger_type, trigger_value = _detect_trigger(left)

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
        # Правило без наказания («Уважайте каждого — приятная атмосфера»).
        # Общие фразы делаем нейро-правилом (ИИ оценивает по тексту),
        # остальные триггеры наказываем предупреждением по умолчанию.
        if trigger_type == "word" and not left.startswith(
            ("слово:", "word:", "слова:", "фраза:", "phrase:")
        ):
            trigger_type, trigger_value = "ai", left
        action = "warn"

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
        raw_text=raw.strip(),
    )
    return rule, None


def parse_rules_bulk(raw: str) -> tuple[list[Rule], list[str]]:
    """Разбирает блок правил (по строке на правило). Возвращает (правила, ошибки)."""
    rules: list[Rule] = []
    errors: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        rule, err = parse_rule(line)
        if rule is None:
            if err:
                errors.append(f"«{line[:60]}» — {err}")
            continue  # заголовки/оформление пропускаем молча
        rules.append(rule)
    return rules, errors


# ---------------------------------------------------------------- matching

from . import detect  # noqa: E402


def rule_matches_text(rule: Rule, text: str) -> bool:
    """Проверка текстовых правил. Семантические (ai) возвращают False —
    их оценивает нейромодуль в handlers_group."""
    t = rule.trigger_type
    if t == "word":
        return bool(rule.trigger_value) and rule.trigger_value.lower() in text.lower()
    if t == "links":
        return detect.has_links(text)
    if t == "mat":
        return detect.has_profanity(text)
    if t == "insult":
        # Упоминание «мошенник/абуз/скам» в жалобе — не оскорбление.
        return detect.has_insult(text) and not detect.has_meta_mention(text)
    if t == "threat":
        return detect.has_threat(text)
    if t == "scam":
        # Предупреждение про «мошенника/скам» само по себе не спам.
        return detect.has_scam(text) and not detect.has_meta_mention(text)
    if t == "nsfw":
        return detect.has_nsfw(text)
    if t == "pii":
        return detect.has_pii(text)
    if t == "caps":
        return detect.has_caps(text)
    if t == "emoji":
        return detect.has_many_emoji(text)
    if t == "nonsense":
        return detect.is_gibberish(text)
    return False


def rule_matches_text_dict(rule: dict, text: str) -> bool:
    return rule_matches_text(Rule.from_dict(rule), text)
