"""Быстрый тест логики (без Telegram). Запуск: python test_logic.py"""

import asyncio
import sys
import time

from src import rules
from src import profanity
from src.storage import Storage


def test_durations():
    cases = {
        "1 час": 3600,
        "30 минут": 1800,
        "5 мин": 300,
        "2 дня": 172800,
        "1 неделя": 604800,
        "навсегда": None,
        "forever": None,
        "3": None,
    }
    for raw, expected in cases.items():
        got = rules.parse_duration(raw)
        assert got == expected, f"duration {raw!r}: got {got}, want {expected}"
    assert rules.format_duration(3600) == "1 час"
    assert rules.format_duration(90) == "1 минута"
    assert rules.format_duration(None) == "навсегда"
    print("[OK] durations")


def test_parse_rule():
    r, err = rules.parse_rule("флуд - мут 1 час")
    assert err is None and r.trigger_type == "flood" and r.action == "mute" and r.duration == 3600, (r, err)
    r, err = rules.parse_rule("реклама - бан")
    assert err is None and r.trigger_type == "links" and r.action == "ban" and r.duration is None, (r, err)
    r, err = rules.parse_rule("мат - мут 30 минут")
    assert err is None and r.trigger_type == "mat" and r.action == "mute" and r.duration == 1800, (r, err)
    r, err = rules.parse_rule("слово:айпи - кик")
    assert err is None and r.trigger_type == "word" and r.trigger_value == "айпи" and r.action == "kick", (r, err)
    r, err = rules.parse_rule("спам - мут 2 часа")
    assert err is None and r.trigger_type == "spam" and r.duration == 7200, (r, err)
    r, err = rules.parse_rule("ссылки - варн")
    assert err is None and r.trigger_type == "links" and r.action == "warn", (r, err)
    # мут без длительности -> 1 час
    r, err = rules.parse_rule("флуд - мут")
    assert err is None and r.duration == 3600, (r, err)
    # наказание с вариантами («кик / бан») — берётся первый, сырой текст сохраняется
    r, err = rules.parse_rule("реклама - мут 1-2 часа / бан")
    assert err is None and r.action == "mute" and r.duration == 7200, (r, err)
    assert r.raw_text == "реклама - мут 1-2 часа / бан", r.raw_text
    assert "мут 1-2 часа / бан" in r.to_context(), r.to_context()
    assert "мут 1-2 часа / бан" in r.to_display(), r.to_display()
    # без тире — заголовок/оформление: (None, None), а не ошибка
    r, err = rules.parse_rule("просто текст без тире")
    assert r is None and err is None, (r, err)
    # неопознанное наказание — берём предупреждение по умолчанию
    r, err = rules.parse_rule("флуд - что-то странное")
    assert err is None and r.trigger_type == "flood" and r.action == "warn", (r, err)
    # общая фраза без наказания превращается в нейро-правило
    r, err = rules.parse_rule("уважайте каждого - приятная атмосфера важнее споров")
    assert err is None and r.trigger_type == "ai" and r.action == "warn", (r, err)
    print("[OK] parse_rule")


def test_parse_chat_rules():
    """Правила в формате «✦ ... Наказание: ...» должны распознаваться."""
    block = """୨୧ Правила чата

✦ Без спама и флуда. Наказание: мут 1-2 часа.
✦ Без оскорблений, травли и унижений. Наказание: мут 1-2 часа / бан.
✦ Не разжигайте конфликты и не провоцируйте участников. Наказание: мут 1 час.
✦ Запрещены угрозы, шантаж и любой вид буллинга. Наказание: мут 1-24 часа / бан.
✦ Не распространяйте ложную информацию и слухи. Наказание: мут 1-3 часа / кик.
✦ Без рекламы, самопиара и ссылок без разрешения. Наказание: кик / бан.
✦ Не отправляйте контент 18+, шокирующие материалы и сцены насилия. Наказание: мут 1-3 часа / бан.
✦ Уважайте личные границы и не публикуйте чужие данные. Наказание: мут 1-6 часов / бан.
✦ Не злоупотребляйте капсом, повторяющимися сообщениями и эмодзи. Наказание: мут 30 минут.
✦ Не засоряйте чат бессмысленными сообщениями. Наказание: мут 1 час.
✦ Запрещены мошенничество, обман и любые попытки навредить участникам. Наказание: бан."""
    parsed, errors = rules.parse_rules_bulk(block)
    assert len(parsed) == 11, f"expected 11 rules, got {len(parsed)}: {errors}"
    types = [r.trigger_type for r in parsed]
    assert types[0] == "flood", types
    assert types[1] == "insult", types
    assert types[2] == "ai", types
    assert types[3] == "threat", types
    assert types[4] == "ai", types
    assert types[5] == "links", types
    assert types[6] == "nsfw", types
    assert types[7] == "pii", types
    assert types[8] == "caps", types
    assert types[9] == "nonsense", types
    assert types[10] == "scam", types
    assert parsed[0].duration == 7200, parsed[0].duration
    print("[OK] parse_chat_rules")


def test_parse_bulk_headers():
    """Заголовки и фразы-правила без наказания не должны попадать в «Пропущено»."""
    block = """୨୧ Правила чата
Флуд - мут 1 час
✦ Уважайте каждого - приятная атмосфера важнее любых споров.
🗓 Правила чата
Без рекламы - бан"""
    parsed, errors = rules.parse_rules_bulk(block)
    assert not errors, errors
    assert len(parsed) == 3, [r.to_context() for r in parsed]
    assert parsed[1].trigger_type == "ai" and parsed[1].action == "warn", parsed[1]
    print("[OK] parse_bulk_headers")


def test_meta_and_links_detect():
    from src import detect

    assert detect.has_meta_mention("он мошенник, не ведитесь")
    assert detect.has_meta_mention("это абуз, удалите")
    assert not detect.has_meta_mention("он мошенничает с цифрами")
    assert detect.has_scam("лохотрон: скидки по ссылке https://t.me/scam")
    links = detect.extract_telegram_links("смотри t.me/NewsChannel и https://t.me/+abc123XYZ")
    assert "NewsChannel" in links and "+abc123XYZ" in links, links
    assert detect.is_invite_link("+abc123XYZ")
    assert not detect.is_invite_link("NewsChannel")
    print("[OK] meta_and_links_detect")


def test_detectors():
    from src import detect

    assert detect.has_caps("ПРИВЕТ ВСЕМ КАК ДЕЛА")
    assert not detect.has_caps("Привет всем как дела")
    assert detect.has_many_emoji("🎉🎉🎉🎉🎉 праздник")
    assert not detect.has_many_emoji("🎉 привет")
    assert detect.has_links("смотри https://example.com")
    assert detect.has_links("подпишись @superchanel")
    assert not detect.has_links("обычный текст")
    assert detect.has_insult("ты вообще идиот тупой")
    assert detect.has_threat("я тебя убью")
    assert detect.has_scam("переведи мне деньги, это выгодно")
    assert detect.has_nsfw("скину порнуху")
    assert detect.has_pii("мой номер +7 900 123-45-67")
    assert detect.is_gibberish("клвпрст клвпрст")
    assert not detect.is_gibberish("привет как дела")
    print("[OK] detectors")


def test_matching():
    r, _ = rules.parse_rule("слово:дискорд - мут 1 час")
    assert rules.rule_matches_text(r, "заходите в наш дискорд!")
    assert not rules.rule_matches_text(r, "обычное сообщение")
    r, _ = rules.parse_rule("реклама - бан")
    assert rules.rule_matches_text(r, "смотри https://example.com")
    assert rules.rule_matches_text(r, "подпишись на @superchanel")
    assert not rules.rule_matches_text(r, "просто текст")
    r, _ = rules.parse_rule("мат - мут 1 час")
    assert rules.rule_matches_text(r, "ты бля такой")
    assert rules.rule_matches_text(r, "ты мой хуй соси")
    assert not rules.rule_matches_text(r, "иди нахуй")
    assert not rules.rule_matches_text(r, "нормальное сообщение")
    assert profanity.contains_profanity("привет блядь")
    assert not profanity.contains_profanity("привет всем")
    print("[OK] matching")


def test_ai_verdict():
    from src.aimod import parse_verdict

    assert parse_verdict('{"violated": false}') == {"violated": False}
    v = parse_verdict(
        '{"violated": true, "rule_index": 2, "action": "mute", '
        '"duration_minutes": 30, "reason": "спам"}'
    )
    assert v["violated"] and v["rule_index"] == 2, v
    assert v["action"] == "mute" and v["duration_minutes"] == 30, v
    # русские названия действий
    v = parse_verdict('{"violated": true, "rule_index": 5, "action": "бан", "duration_minutes": null}')
    assert v["action"] == "ban" and v["duration_minutes"] is None, v
    v = parse_verdict('{"violated": true, "rule_index": 3, "action": "выгнать"}')
    assert v["action"] == "kick", v
    # текст вокруг JSON
    assert parse_verdict('Вот ответ: {"violated": false} конец') == {"violated": False}
    # мусор
    assert parse_verdict("привет") is None
    assert parse_verdict(None) is None
    assert parse_verdict('{"action": "ban"}') is None
    print("[OK] ai verdict")


async def test_storage():
    s = Storage()
    # принудительно SQLite во временный файл (обойдём DATABASE_URL из env)
    import os
    os.environ.pop("DATABASE_URL", None)
    import importlib
    import tempfile
    import src.storage as st
    importlib.reload(st)
    st.DATABASE_URL = ""
    st.SQLITE_PATH = os.path.join(tempfile.gettempdir(), "test_storage.db")
    try:
        os.remove(st.SQLITE_PATH)
    except OSError:
        pass
    s2 = st.Storage()
    await s2.connect()
    await s2.upsert_chat(-100123, "Мой чат", "mychat")
    await s2.set_chat_enabled(-100123, True)
    chats = await s2.get_chats()
    assert len(chats) == 1 and chats[0]["enabled"] == 1
    rid = await s2.add_rule(-100123, "flood", None, "mute", 3600, "флуд - мут 1 час")
    rules_rows = await s2.get_rules(-100123)
    assert len(rules_rows) == 1 and rules_rows[0]["action"] == "mute"
    assert rules_rows[0]["raw_text"] == "флуд - мут 1 час", rules_rows[0]
    assert await s2.get_rule(rid) is not None
    await s2.delete_rule(rid)
    assert len(await s2.get_rules(-100123)) == 0
    c = await s2.add_warning(-100123, 555)
    assert c == 1
    c = await s2.add_warning(-100123, 555)
    assert c == 2
    await s2.reset_warnings(-100123, 555)
    assert await s2.get_warnings(-100123, 555) == 0
    s3 = await s2.get_settings(-100123)
    assert s3["warn_limit"] == 3
    assert s3["ai_mode"] == 0 and s3["ai_cooldown"] == 20, s3
    await s2.update_setting(-100123, "warn_limit", 5)
    assert (await s2.get_settings(-100123))["warn_limit"] == 5
    await s2.update_setting(-100123, "ai_mode", 1)
    assert (await s2.get_settings(-100123))["ai_mode"] == 1
    await s2.remove_chat(-100123)
    assert len(await s2.get_chats()) == 0
    await s2.close()
    print("[OK] storage")


def test_split_duration_reason():
    from src.handlers_group import _split_duration_reason

    assert _split_duration_reason("") == (None, "")
    assert _split_duration_reason("2 часа спам") == (7200, "спам")
    assert _split_duration_reason("30 минут капс") == (1800, "капс")
    assert _split_duration_reason("навсегда реклама") == (None, "реклама")
    assert _split_duration_reason("просто причина") == (None, "просто причина")
    assert _split_duration_reason("- 1 день мат") == (86400, "мат")
    print("[OK] split_duration_reason")


async def test_warn_expiry():
    import os
    import tempfile
    import src.storage as st
    st.DATABASE_URL = ""
    st.SQLITE_PATH = os.path.join(tempfile.gettempdir(), "test_expiry.db")
    try:
        os.remove(st.SQLITE_PATH)
    except OSError:
        pass
    s = st.Storage()
    await s.connect()
    now = int(time.time())
    # без срока — считаются до лимита
    assert await s.add_warning(-100999, 1) == 1
    assert await s.add_warning(-100999, 1) == 2
    # срок истёк — предыдущие снимаются
    assert await s.add_warning(-100999, 2, now - 10) == 1
    assert await s.add_warning(-100999, 2, now - 10) == 1
    # срок в будущем — копятся
    assert await s.add_warning(-100999, 3, now + 3600) == 1
    assert await s.add_warning(-100999, 3, now + 3600) == 2
    await s.close()
    print("[OK] warn_expiry")


if __name__ == "__main__":
    test_durations()
    test_parse_rule()
    test_parse_chat_rules()
    test_detectors()
    test_matching()
    test_ai_verdict()
    test_split_duration_reason()
    asyncio.run(test_storage())
    asyncio.run(test_warn_expiry())
    print("\nALL TESTS PASSED ✅")
