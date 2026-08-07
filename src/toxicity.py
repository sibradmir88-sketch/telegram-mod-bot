"""Наша собственная нейросеть: классификатор токсичности (RuBERT-tiny2).

Обучается скриптом train_toxicity.py, результат — models/toxic_classifier/.
Работает локально, без интернета, API-ключей и лимитов.

Использование:
    from .toxicity import classify
    verdict = classify("ты тупой")   # -> {"toxic": True, "prob": 0.97}
"""

import os
import time

_MODEL = None
_TOKENIZER = None
_LOAD_TIME = 0.0

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "toxic_classifier")
MAX_LEN = 96
# Порог: ниже — считаем «не токсично». 0.6 даёт меньше ложных срабатываний.
THRESHOLD = float(os.getenv("TOXICITY_THRESHOLD", "0.6"))

# Слова-триггеры: сообщение, где НЕТ ничего из них, классификатор не проверит
# (экономия времени; сами регексы мата/обфускаций всё равно отработают раньше).
_FAST_PASS_HINTS = (
    "хуй", "хуя", "хуе", "пизд", "бля", "ебал", "еба", "ёб", "ебн", "еб",
    "мудак", "мудил", "гандон", "гондон", "долбо", "далбо", "дебил", "туп",
    "соси", "сосал", "отсос", "шлюх", "простит", "пидор", "петух", "педик",
    "лох", "лошар", "урод", "сволоч", "тварь", "мразь", "ублюд", "козёл",
    "сука", "тёлка", "шмара", "блядь", "чмо", "чмошн", "дурак", "идиот",
    "кретин", "имбецил", "тупиц", "олень", "овца", "баран", "животн",
    "дегенерат", "кончен", "уёб", "уебок", "ёбну", "аху", "нах", "zалyп",
    "хyй", "пиздa", "блядь", "ебё", "ёбaн", "разъеб", "заеб",
)


def is_available() -> bool:
    return os.path.isdir(MODEL_DIR)


def _load():
    """Ленивая загрузка модели (первый вызов медленный ~2-5 сек)."""
    global _MODEL, _TOKENIZER, _LOAD_TIME
    if _MODEL is not None:
        return True
    if not is_available():
        return False
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    _TOKENIZER = AutoTokenizer.from_pretrained(MODEL_DIR)
    _MODEL = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    _MODEL.eval()
    _LOAD_TIME = time.time()
    return True


def _maybe_fast_pass(text: str) -> bool:
    """Если в тексте нет ни одного матерного/оскорбительного триггера
    И ни одного маркера оскорбления — пропустить (модель не вызываем).
    Маркеры проверяем тоже: «ничтожество» может не быть в триггерах,
    но это явное оскорбление."""
    low = text.lower()
    if any(m in low for m in _ADDRESS_MARKERS):
        return False
    return not any(h in low for h in _FAST_PASS_HINTS)


def classify(text: str) -> dict:
    """Классификация текста на токсичность.

    Возвращает {"toxic": bool, "prob": float, "error": None|str}.
    Если модель недоступна — {"toxic": False, "prob": 0.0, "error": "model unavailable"}.
    """
    if not _load():
        return {"toxic": False, "prob": 0.0, "error": "model unavailable"}
    if not text or not text.strip():
        return {"toxic": False, "prob": 0.0, "error": None}
    if _maybe_fast_pass(text):
        return {"toxic": False, "prob": 0.0, "error": None}

    try:
        import torch
        enc = _TOKENIZER(
            text,
            truncation=True,
            max_length=MAX_LEN,
            padding="max_length",
            return_tensors="pt",
        )
        with torch.no_grad():
            logits = _MODEL(**enc).logits
        prob = float(torch.softmax(logits, dim=-1)[0, 1].item())
        return {"toxic": prob >= THRESHOLD, "prob": prob, "error": None}
    except Exception as e:
        return {"toxic": False, "prob": 0.0, "error": str(e)}


def unload():
    """Выгрузка модели из памяти (экономия RAM при долгом простое)."""
    global _MODEL, _TOKENIZER
    _MODEL = None
    _TOKENIZER = None


# Маркеры адресации оскорбления к человеку (по нашей политике наказываем только
# оскорбления, а не «мат-паразит» типа «блядь, ну нахуй эту доту»).
# НЕ включаем нейтральные «ты/тебя/твой» — они встречаются в безобидных фразах.
_ADDRESS_MARKERS = (
    "урод", "дебил", "идиот", "мудак", "долбоёб", "долбоеб", "долбаёб",
    "тупой", "тупая", "тупое", "тупы", "тупор", "шлюх", "петух", "пидор",
    "педик", "соси", "отсос", "чмо", "лох", "лошар", "мразь", "тварь",
    "ублюд", "козёл", "козел", "сволоч", "гандон", "гондон", "кончен",
    "уёб", "уеб", "уёб", "ебан", "ёбан", "ебаный", "ёбаный", "ебаная",
    "дурак", "кретин", "имбецил", "олень", "баран", "овца", "корова",
    "животн", "дегенерат", "выродок", "придурок", "недоумок", "утырок",
    "собака", "пёс", "псина", "скотин", "гад", "сволочь", "шваль",
    "ничтожеств", "убожеств", "отродье", "мразот", "шестёрка", "ссанина",
    "залуп", "херня", "хуесос", "хуесо", "хуила", "хуйло", "хуйня",
    "мудачина", "козлина", "дубина", "балда", "толстожоп", "кривожоп",
    "уродина", "страшил", "пугало", "обезьян", "осёл", "свинья", "свин",
)

# Токенизатор нашей модели ловит обфускации слабо, поэтому для искажённых
# слов (лесенка «Т\nЫ\nЧ\nМ\nО\nК\nА», «долбоеь», «туопйрылый», «тупооой»,
# латиница-подмена «zалyп») добавляем нечёткий матч. Он ловит ТОЛЬКО искажения,
# а обычные слова («нахуй», «блядь», «тупой») оставляет модели и маркерам.
_FUZZY_BASES = (
    "долбо", "тупор", "тупой", "дебил", "идиот", "мудак", "урод", "ебан",
    "уёб", "уеб", "ебал", "соси", "чмо", "мраз", "тварь", "лох", "пидор",
    "петух", "хуй", "хуя", "хуе", "пизд", "бля", "муд", "сук",
)

# Оскорбления-НЕ-мат: если такая база есть в нормализованном тексте, но не
# встречается обычным словом — это намеренное искажение (сигнал). Мат-базы
# («хуй», «бля», «пизд») сюда НЕ входят: «нахуй», «блядь» — обычные паразиты.
_INSULT_BASES = (
    "долбо", "тупор", "тупой", "дебил", "идиот", "мудак", "урод", "чмо",
    "мраз", "тварь", "лох", "дурак", "козел", "соси", "пидор", "петух",
    "залуп", "хуйло", "хуесос",
)

# Подмена латинских букв русскими в мате/оскорблениях («zалyп» = «залуп»).
_LAT_TO_CYR = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
                             "x": "х", "y": "у", "z": "з", "k": "к", "m": "м",
                             "t": "т", "s": "с", "b": "в", "h": "н", "u": "и"})


def _normalize(low: str) -> str:
    """Транслит латиницы, удаление всего не-буквенного (лесенка, пробелы),
    схлопывание повторяющихся букв («тупооой» -> «тупой», «ссука» -> «сука»)."""
    import re
    t = low.translate(_LAT_TO_CYR)
    t = re.sub(r"[^а-яёa-z]+", "", t)
    out = []
    for ch in t:
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def _has_fuzzy_insult(low: str) -> bool:
    """Ищет ИСКАЖЁННЫЕ формы оскорблений:
    A) база есть в нормализованном тексте, но не как обычное слово в исходном
       («тупооой», лесенка «ЧМОКА», «zалyп»);
    B) перестановка одной пары соседних букв («туопйрылый»=«тупой»,
       «ухй»=«хуй», «омйо»=«чмо») в исходном или нормализованном тексте.
    Обычные формы («нахуй», «блядь», «какой тупой фильм») НЕ сигнал —
    их оценивают модель и маркеры."""
    norm = _normalize(low)
    if any(b in norm for b in _INSULT_BASES) and not any(b in low for b in _INSULT_BASES):
        return True
    for base in _FUZZY_BASES:
        if len(base) < 3:
            continue
        for i in range(len(base) - 1):
            v = base[:i] + base[i + 1] + base[i] + base[i + 2:]
            if v in low or v in norm:
                return True
    return False


def analyze(text: str) -> dict | None:
    """Вердикт нашей модели в формате aimod.analyze_message().

    None — не нарушение (или модель недоступна). Нарушение — только оскорбление
    человека: токсичность выше порога И (оскорбительный маркер или его
    обфусцированная форма). Обычный мат-паразит («блядь, ну нахуй эту доту»)
    и безобидные фразы («как тебя зовут?») — пропуск.
    """
    if not text or not text.strip():
        return None
    low = text.lower()
    # 1) обфусцированное оскорбление («долбоеь», «туопйрылый», лесенка) —
    #    ловим ДО модели: модель такие буквы не всегда понимает
    if _has_fuzzy_insult(low):
        return {
            "violated": True, "rule_index": None,
            "action": "mute", "duration_minutes": 60,
            "reason": "оскорбление",
            "prob": 1.0,
        }
    # 2) обычное оскорбление — наша модель
    r = classify(text)
    if r["error"] or not r["toxic"]:
        return None
    prob = r["prob"]
    marked = any(m in low for m in _ADDRESS_MARKERS)
    if not marked or prob < THRESHOLD:
        return None
    return {
        "violated": True, "rule_index": None,
        "action": "mute", "duration_minutes": 60,
        "reason": "оскорбление",
        "prob": prob,
    }


if __name__ == "__main__":
    # Быстрый тест
    tests = [
        "привет как дела",
        "ты тупой урод",
        "ПРИВЕТТЬТ КАК ЕЛАД ДАВАЙ В ДОТУ",
        "ТЫ ТУОПЙРЫЛЫЙ СНЫОК ШАЛБЮХИ ЕБАЕНОЙ",
        "бля ну нахуй эту доту",
        "долбоеь ебаный",
    ]
    for t in tests:
        print(repr(t[:40]), "->", classify(t))
