"""Локальные детекторы нарушений (работают без нейросети и API)."""

import itertools
import re

from . import profanity

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|[\w.-]+\.(ru|com|net|org|io|xyz|top|site|pro|info)\b|(?<!\w)@[a-zA-Z0-9_]{4,})", re.I)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+7|8|7)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
CARD_RE = re.compile(r"\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}")

# Заготовки эмодзи: широкие диапазоны Unicode
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u00a9\u00ae\u203c\u2049\u2122\u2139\u2194-\u21aa\u2328\u23cf"
    "\u23e9-\u23f3\u23f8-\u23fa\u24c2\u25aa\u25ab\u25b6\u25c0"
    "\u25fb-\u25fe\u2600-\u26ff\u2700-\u27bf\u2934\u2935\u2b05-\u2b07"
    "\u2b1b\u2b1c\u2b50\u2b55\u3030\u303d\u3297\u3299]"
)

_NSFW = ("порн", "секс", "18+", "интим", "обнаж", "эрот", "насил", "кровь",
         "труп", "жесток", "расчлен", "убийств", "самоуб", "шок-контент")
_THREATS = ("убью", "урою", "прибью", "завалю", "приконч", "зарежу", "сожг",
            "взломаю", "сломаю", "шантаж", "угрож", "запуг", "расправ", "найду и")
_SCAM = ("переведи", "скинь", "лохотрон", "развод", "афера", "выигрыш", "приз",
         "промокод", "майнинг", "инвест", "вклад под", "халяв", "нахаляву",
         "пирамид", "легкий заработок", "уникальная возможность", "успей", "вложи")
_PII = ("паспорт", "снилс", "инн", "серия", "номер карты", "код с карты",
        "пин-код", "код подтверждения", "номер телефона", "адрес", "прописк")
_INS = ("урод", "тупиц", "дурак", "дуро", "глуп", "отстой", "ничтожество", "убог")

# Слова, которые люди используют в обвинениях/предупреждениях («он мошенник»),
# но сами по себе они не должны вызывать наказание.
_META_SAFE_RE = re.compile(
    r"(?<![а-яёa-z])(?:мошенник|мошенниц|абуз|абьюз|кидал|жулик|скам|лохотрон|"
    r"развод|разводил|обман|фейк)(?![а-яёa-z])",
    re.I,
)

_TME_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/([^\s<>\"')]+)", re.I
)
_AT_USER_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,})")

_VOWELS = set("аеёиоуыэюяaeiouy")


def _low(text: str) -> str:
    return text.lower().replace("ё", "е")


def has_meta_mention(text: str) -> bool:
    """Текст упоминает «мошенника/абуз/скам» и т.п. — например, жалоба или предупреждение."""
    return bool(_META_SAFE_RE.search(text))


def extract_telegram_links(text: str) -> list[str]:
    """Достаёт из текста сегменты t.me/telegram.me ссылок (включая инвайты вида +…)."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _TME_LINK_RE.finditer(text):
        seg = m.group(1).split("?")[0].strip(".,;:!?)»«\"'")
        if not seg or seg in seen:
            continue
        if seg.startswith(("addstickers/", "addtheme/", "addemoji/", "share", "bg")):
            continue
        seen.add(seg)
        out.append(seg)
    return out


def extract_mentions(text: str) -> list[str]:
    """Достаёт из текста упоминания вида @username."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _AT_USER_RE.finditer(text):
        u = m.group(1)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_invite_link(handle: str) -> bool:
    h = handle.lower()
    return h.startswith(("+", "joinchat/", "s/", "proxy/"))


def has_caps(text: str, min_letters: int = 5, threshold: float = 0.55) -> bool:
    """Более половины букв заглавные (и букв не меньше min_letters)."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < min_letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= threshold


def emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text))


def has_many_emoji(text: str, limit: int = 4) -> bool:
    return emoji_count(text) >= limit


def has_links(text: str) -> bool:
    return bool(URL_RE.search(text))


def has_profanity(text: str) -> bool:
    return profanity.contains_profanity(text)


def has_insult(text: str) -> bool:
    low = _low(text)
    return profanity.contains_profanity(text) or any(w in low for w in _INS)


def has_threat(text: str) -> bool:
    low = _low(text)
    return any(w in low for w in _THREATS)


def has_scam(text: str) -> bool:
    low = _low(text)
    return any(w in low for w in _SCAM)


def has_nsfw(text: str) -> bool:
    low = _low(text)
    return any(w in low for w in _NSFW)


def has_pii(text: str) -> bool:
    return bool(PHONE_RE.search(text) or EMAIL_RE.search(text) or CARD_RE.search(text)
                or any(w in _low(text) for w in _PII))


def is_gibberish(text: str) -> bool:
    """Бессмысленный текст: клавиатурный мусор, без гласных, длинные повторы."""
    raw = text.strip()
    t = re.sub(r"[^a-zа-яё0-9]", "", _low(raw))
    if len(t) < 6:
        return False
    v = sum(1 for c in t if c in _VOWELS)
    if v == 0:
        return True
    if v / len(t) < 0.12:
        return True
    for _ch, group in itertools.groupby(t):
        if sum(1 for _ in group) >= 6:
            return True
    for _ch, group in itertools.groupby(raw):
        n = sum(1 for _ in group)
        if n >= 8 and not _ch.isalnum():
            return True
    return False
