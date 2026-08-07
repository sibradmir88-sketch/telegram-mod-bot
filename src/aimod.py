"""Опциональная нейро-модерация через внешний OpenAI-совместимый API.

Основной режим модератора — встроенная нейросеть (src/toxicity.py), внешний
API не нужен. Этот модуль остался для будущего: GigaChat, OpenAI, Qwen и т.п.
Включение: задать в .env  AI_API_URL, AI_API_KEY, AI_MODEL.
Без настройки умный режим работает на встроенной модели.

Режимы:
- moderate()        — проверка одного правила (True/False) для триггеров «ai»;
- analyze_message() — умный режим: ИИ смотрит сообщение по ВСЕМ правилам чата и
  сам выбирает наказание из вариантов правила (например «кик / бан»).
"""

import json
import re
import time
import uuid
from urllib.parse import urlparse

import aiohttp

from .config import (
    AI_API_KEY,
    AI_API_URL,
    AI_MODEL,
    AI_OAUTH_SCOPE,
    AI_OAUTH_URL,
    AI_TIMEOUT,
    BOT_PROXY,
)

_giga_token_cache: str | None = None
_giga_token_cache_exp = 0.0

ACTION_ALIASES = {
    "мут": "mute",
    "мута": "mute",
    "мьют": "mute",
    "mute": "mute",
    "бан": "ban",
    "бана": "ban",
    "забанить": "ban",
    "банх": "ban",
    "ban": "ban",
    "кик": "kick",
    "выгнать": "kick",
    "вылет": "kick",
    "kick": "kick",
    "варн": "warn",
    "предупреждение": "warn",
    "предупредить": "warn",
    "warn": "warn",
}


def is_configured() -> bool:
    return bool(AI_API_URL and AI_API_KEY)


def _is_giga() -> bool:
    return "giga.chat" in AI_API_URL or "sberbank.ru" in AI_API_URL


def _should_use_proxy() -> bool:
    """Прокси нужен только если провайдер недоступен напрямую из РФ.
    Часть API ходит из РФ напрямую, а через WARP-IP (датацентр) отдаёт 402."""
    if not BOT_PROXY:
        return False
    host = urlparse(AI_API_URL).hostname or ""
    for direct_host in ("giga.chat", "sberbank.ru", "huggingface.co", "sambanova.ai", "api.cloudflare.com", "localhost", "127.0.0.1"):
        if direct_host in host:
            return False
    return True


def _make_connector():
    if _should_use_proxy():
        from aiohttp_socks import ProxyConnector
        return ProxyConnector.from_url(BOT_PROXY)
    return None


async def _giga_token(session: aiohttp.ClientSession, force: bool = False) -> str | None:
    """Возвращает (и кэширует) access token GigaChat. Токен живёт 30 минут."""
    global _giga_token_cache, _giga_token_cache_exp
    now = time.time()
    if not force and _giga_token_cache and _giga_token_cache_exp > now + 60:
        return _giga_token_cache
    payload = f"scope={AI_OAUTH_SCOPE}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {AI_API_KEY}",
    }
    async with session.post(
        AI_OAUTH_URL,
        data=payload,
        headers=headers,
        ssl=False,
        timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT),
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json(content_type=None)
    _giga_token_cache = data.get("access_token")
    try:
        _giga_token_cache_exp = float(data.get("expires_at", 0)) / 1000.0
    except (TypeError, ValueError):
        _giga_token_cache_exp = now + 1500
    return _giga_token_cache


async def _chat(prompt: str, max_tokens: int = 250, json_mode: bool = False) -> str | None:
    """Один запрос к чат-API. Возвращает текст ответа или None при ошибке."""
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    # json_object поддерживают не все API. Локальная Ollama
    # (localhost/127.0.0.1) понимает свой "format": "json".
    if json_mode:
        if "127.0.0.1" in AI_API_URL or "localhost" in AI_API_URL:
            payload["format"] = "json"
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    giga = _is_giga()
    connector = _make_connector()
    ssl_kw = {"ssl": False} if giga else {}
    async with aiohttp.ClientSession(connector=connector) as session:
        if giga:
            token = await _giga_token(session)
            if not token:
                return None
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with session.post(
                AI_API_URL,
                headers=headers,
                json=payload,
                **ssl_kw,
                timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT),
            ) as resp:
                if resp.status == 401 and giga:
                    token = await _giga_token(session, force=True)
                    if not token:
                        return None
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    resp = await session.post(
                        AI_API_URL,
                        headers=headers,
                        json=payload,
                        **ssl_kw,
                        timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT),
                    )
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                return data["choices"][0]["message"]["content"]
        except Exception:
            return None


def parse_verdict(raw: str) -> dict | None:
    """Разбирает JSON-ответ ИИ в словарь-вердикт. None — не смогли понять.

    Успешные вердикты:
      {"violated": False}
      {"violated": True, "rule_index": 2, "action": "mute",
       "duration_minutes": 30, "reason": "спам"}
    """
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    if data.get("violated") in (False, 0, "false", "no"):
        return {"violated": False}

    if data.get("violated") not in (True, 1, "true", "yes"):
        return None

    action_raw = str(data.get("action") or "").strip().lower()
    action = ACTION_ALIASES.get(action_raw)

    dm = data.get("duration_minutes")
    try:
        duration_minutes = int(float(dm))
    except (TypeError, ValueError):
        duration_minutes = None

    try:
        rule_index = int(data.get("rule_index"))
    except (TypeError, ValueError):
        rule_index = None

    return {
        "violated": True,
        "rule_index": rule_index,
        "action": action,
        "duration_minutes": duration_minutes,
        "reason": str(data.get("reason") or "").strip(),
    }


async def moderate(rule_desc: str, text: str) -> bool:
    """Возвращает True, если сообщение нарушает описанное правило."""
    if not is_configured():
        return False
    rule_desc = (rule_desc or "правила чата").strip() or "правила чата"
    prompt = (
        "Ты — строгий модератор Telegram-чата. "
        f"Правило: «{rule_desc[:300]}». "
        f"Сообщение участника: «{text[:400]}». "
        "Оценивай обфусцированный мат (переставленные буквы, опечатки, мат по буквам, "
        "лесенкой) по смыслу: добрые сообщения с опечатками — не нарушение, "
        "оскорбление человека — нарушение. "
        "Нарушает ли это сообщение правило? Ответь строго одним словом: «да» или «нет»."
    )
    answer = await _chat(prompt, max_tokens=5)
    if answer is None:
        return False
    return answer.strip().lower().startswith(("да", "yes", "наруша"))


async def analyze_message(rules_context: str, text: str, extra: str = "") -> dict | None:
    """Умный режим: проверяет сообщение по всем правилам чата и выбирает наказание.

    extra — дополнительный контекст: ссылки и подписчики каналов, фото, пересылки.
    Возвращает None, если ИИ недоступен/ошибка (тогда применяется обычная логика),
    либо вердикт от parse_verdict().
    """
    if not is_configured():
        return None
    prompt = (
        "Ты — модератор Telegram-чата. Ниже правила чата, сообщение участника "
        "и дополнительная информация (ссылки, фото, пересылки).\n\n"
        f"ПРАВИЛА ЧАТА:\n{rules_context[:2500]}\n\n"
        f"СООБЩЕНИЕ УЧАСТНИКА: «{text[:600]}»\n"
    )
    if extra:
        prompt += f"\nДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ:\n{extra[:1500]}\n"
    prompt += (
        "\nОпредели, нарушает ли сообщение какие-то из правил.\n"
        "Если нарушено СРАЗУ НЕСКОЛЬКО правил (например флуд + оскорбление + спам) — "
        "не выбирай одно, а сложи всё вместе и выдай ОДНО итоговое наказание строже: "
        "например вместо «мут 1-2 часа» — «мут 3-6 часов», при грубом наборе нарушений "
        "— бан, кик или предупреждение на время.\n"
        "Если нарушает: выбери НОМЕР главного нарушенного правила (rule_index из списка) "
        "и наказание ИЗ ВАРИАНТОВ этого правила, если они есть. Например, если в правиле "
        "указано «кик / бан» — выбери одно из них. Наказание выбирай по тяжести: "
        "за лёгкое — мягче, за жёсткое — строже.\n"
        "Жёсткие нарушения (реклама чужого канала/чата, угрозы, шантаж, обман) → бан.\n"
        "Правила:\n"
        "• Простое упоминание слов «мошенник», «абуз», «скам» и т.п. (жалоба или "
        "предупреждение других) — НЕ нарушение.\n"
        "• Анатомические и медицинские слова («вагина», «пенис», «член», «грудь», "
        "«яйца», «попа», «влагалище») сами по себе НЕ мат и НЕ оскорбление — "
        "не наказывай, если ими не оскорбляют человека напрямую.\n"
        "• Обычный мат (слова-паразиты и восклицания: «блядь», «нахуй», «пиздец», "
        "«ёбаный» сами по себе, без оскорбления человека) — НЕ нарушение.\n"
        "• Нарушение — только ОСКОРБЛЕНИЕ: брань, направленная на человека "
        "(«ты тупорылый», «соси хуй, урод», «ты шлюха ебаная»). Оскорбление наказывай, "
        "даже если в сообщении нет @ник, ответа или слова «ты» — если брань очевидно "
        "адресована кому-то или звучит как оскорбление.\n"
        "• Обфусцированный мат (переставленные буквы, опечатки, мат по буквам, "
        "через пробелы, «лесенкой») — не бессмыслица. Оценивай ПО СМЫСЛУ: доброе или "
        "нейтральное сообщение с опечатками («ПРИВЕТТЬТ КАК ЕЛАД», «СЛЫШИЛЬ НАЗУЙ КАК У "
        "ТЕБЯ ДЕЛА») — НЕ нарушение, даже если в нём что-то похоже на мат. Если это "
        "оскорбление («ТЫ ТУОПЙРЫЛЫЙ СНЫОК ШАЛБЮХИ ЕБАЕНОЙ») — нарушение, наказывай.\n"
        "• Главный принцип: суди ПО СМЫСЛУ всего сообщения, а не по отдельным похожим "
        "на мат буквосочетаниям. Приветствие, вопрос «как у тебя дела», комплимент, "
        "нейтральная фраза — НЕ нарушение, даже если в тексте есть опечатки или "
        "случайные обрывки, похожие на мат.\n"
        "• Фраза «иди на хуй» и её формы («иди нахуй», «иди нахер», «иди нафиг») — "
        "обычное разговорное выражение в этом чате, НЕ нарушение.\n"
        "• Ссылка на канал со 100 000+ подписчиков (новостной) — НЕ нарушение.\n"
        "• Ссылка-приглашение или ссылка на маленький канал/чат с целью продвижения — бан.\n"
        "• Короткие сообщения и междометия («f», «k», «ж», «да», «ок», «лол», «ха», «ааа») "
        "— НЕ нарушение. Это обычное общение.\n"
        "• «Бессмыслица/мусор» — это длинные бессвязные строки, клавиатурный мусор "
        "или бесконечные повторы, а НЕ короткие мемы и междометия. Обфусцированный "
        "мат — не бессмыслица, оценивай его по смыслу (см. правила выше).\n"
        "• НЕ выдумывай нарушений. Если сомневаешься или сообщение безобидное — "
        "возвращай {\"violated\": false}.\n"
        "• За первое мелкое нарушение наказание должно быть мягким: предупреждение "
        "или короткий мут (до 30 минут), не бан и не долгий мут за мелочь.\n"
        "• Мут НИКОГДА не выдавай навсегда и не длиннее 24 часов: duration_minutes "
        "от 1 до 1440 (максимум 1440 = 24 часа).\n"
        "• Бан: от 1 дня (1440 минут) до 14 дней (20160 минут), либо навсегда "
        "(duration_minutes: null) только за очень грубое нарушение (реклама, угрозы, "
        "шантаж, обман). Не бани за мелкие нарушения.\n"
        "• Флуд и спам (много одинаковых коротких сообщений подряд) — нарушение, "
        "даже если сами сообщения безобидные междометия («f», «k», «да»).\n"
        "Ответь СТРОГО одним JSON-объектом, без пояснений и текста вокруг:\n"
        '{"violated": true, "rule_index": <номер главного правила или null>, '
        '"action": "mute|ban|kick|warn", "duration_minutes": <целое число или null>, '
        '"reason": "<кратко почему>"}\n'
        'Если сообщение в порядке: {"violated": false}'
    )
    answer = await _chat(prompt, max_tokens=400, json_mode=True)
    return parse_verdict(answer or "")
