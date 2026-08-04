"""Быстрый тест логики (без Telegram). Запуск: python test_logic.py"""

import asyncio
import sys

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
    # ошибочные
    r, err = rules.parse_rule("просто текст без тире")
    assert err is not None, "should fail without dash"
    r, err = rules.parse_rule("флуд - что-то странное")
    assert err is not None, "should fail unknown action"
    print("[OK] parse_rule")


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
    assert rules.rule_matches_text(r, "иди нахуй")
    assert not rules.rule_matches_text(r, "нормальное сообщение")
    assert profanity.contains_profanity("привет блядь")
    assert not profanity.contains_profanity("привет всем")
    print("[OK] matching")


async def test_storage():
    s = Storage()
    # принудительно SQLite во временный файл (обойдём DATABASE_URL из env)
    import os
    os.environ.pop("DATABASE_URL", None)
    import importlib
    import src.storage as st
    importlib.reload(st)
    st.DATABASE_URL = ""
    s2 = st.Storage()
    await s2.connect()
    await s2.upsert_chat(-100123, "Мой чат", "mychat")
    await s2.set_chat_enabled(-100123, True)
    chats = await s2.get_chats()
    assert len(chats) == 1 and chats[0]["enabled"] == 1
    rid = await s2.add_rule(-100123, "flood", None, "mute", 3600)
    rules_rows = await s2.get_rules(-100123)
    assert len(rules_rows) == 1 and rules_rows[0]["action"] == "mute"
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
    await s2.update_setting(-100123, "warn_limit", 5)
    assert (await s2.get_settings(-100123))["warn_limit"] == 5
    await s2.remove_chat(-100123)
    assert len(await s2.get_chats()) == 0
    await s2.close()
    print("[OK] storage")


if __name__ == "__main__":
    test_durations()
    test_parse_rule()
    test_matching()
    asyncio.run(test_storage())
    print("\nALL TESTS PASSED ✅")
