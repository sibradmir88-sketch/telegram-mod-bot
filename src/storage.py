"""Хранилище данных: SQLite (по умолчанию) или Postgres (DATABASE_URL).

На Render бесплатный диск эфемерный, поэтому для сохранения правил между
перезапусками лучше подключить бесплатную Postgres (Neon/Supabase) и указать
переменную DATABASE_URL. Если она пуста — бот работает на SQLite.
"""

import re
import time

from .config import (
    DATABASE_URL,
    DEFAULT_FLOOD_MESSAGES,
    DEFAULT_FLOOD_SECONDS,
    DEFAULT_SPAM_MESSAGES,
    DEFAULT_SPAM_SECONDS,
    DEFAULT_WARN_LIMIT,
    DEFAULT_WARN_MUTE_MIN,
)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    enabled INTEGER DEFAULT 0,
    joined_at INTEGER
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_value TEXT,
    action TEXT NOT NULL,
    duration INTEGER,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    delete_on_violation INTEGER DEFAULT 1,
    notify_group INTEGER DEFAULT 1,
    warn_limit INTEGER DEFAULT 3,
    warn_mute_min INTEGER DEFAULT 60,
    flood_messages INTEGER DEFAULT 5,
    flood_seconds INTEGER DEFAULT 10,
    spam_messages INTEGER DEFAULT 3,
    spam_seconds INTEGER DEFAULT 20,
    punish_admins INTEGER DEFAULT 0
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id BIGINT PRIMARY KEY,
    title TEXT,
    username TEXT,
    enabled INTEGER DEFAULT 0,
    joined_at BIGINT
);
CREATE TABLE IF NOT EXISTS rules (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_value TEXT,
    action TEXT NOT NULL,
    duration BIGINT,
    created_at BIGINT
);
CREATE TABLE IF NOT EXISTS warnings (
    chat_id BIGINT,
    user_id BIGINT,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS settings (
    chat_id BIGINT PRIMARY KEY,
    delete_on_violation INTEGER DEFAULT 1,
    notify_group INTEGER DEFAULT 1,
    warn_limit INTEGER DEFAULT 3,
    warn_mute_min INTEGER DEFAULT 60,
    flood_messages INTEGER DEFAULT 5,
    flood_seconds INTEGER DEFAULT 10,
    spam_messages INTEGER DEFAULT 3,
    spam_seconds INTEGER DEFAULT 20,
    punish_admins INTEGER DEFAULT 0
);
"""

VALID_SETTING_KEYS = {
    "delete_on_violation",
    "notify_group",
    "punish_admins",
    "warn_limit",
    "warn_mute_min",
    "flood_messages",
    "flood_seconds",
    "spam_messages",
    "spam_seconds",
}

DEFAULT_SETTINGS = {
    "chat_id": 0,
    "delete_on_violation": 1,
    "notify_group": 1,
    "warn_limit": DEFAULT_WARN_LIMIT,
    "warn_mute_min": DEFAULT_WARN_MUTE_MIN,
    "flood_messages": DEFAULT_FLOOD_MESSAGES,
    "flood_seconds": DEFAULT_FLOOD_SECONDS,
    "spam_messages": DEFAULT_SPAM_MESSAGES,
    "spam_seconds": DEFAULT_SPAM_SECONDS,
    "punish_admins": 0,
}


def _adapt(sql: str, dialect: str) -> str:
    """Переводит '?' в '$1' для Postgres."""
    if dialect != "postgres":
        return sql
    counter = 0

    def _repl(_m: re.Match) -> str:
        nonlocal counter
        counter += 1
        return f"${counter}"

    return re.sub(r"\?", _repl, sql)


class Storage:
    def __init__(self) -> None:
        self._dialect = "sqlite"
        self._sqlite = None
        self._pg = None

    async def connect(self) -> None:
        if DATABASE_URL:
            import asyncpg

            self._dialect = "postgres"
            self._pg = await asyncpg.connect(DATABASE_URL)
            await self._pg.execute(POSTGRES_SCHEMA)
        else:
            import aiosqlite

            self._dialect = "sqlite"
            self._sqlite = await aiosqlite.connect("moderator.db")
            self._sqlite.row_factory = aiosqlite.Row
            await self._sqlite.executescript(SQLITE_SCHEMA)
            await self._sqlite.commit()

    async def _execute(self, sql: str, *params):
        sql = _adapt(sql, self._dialect)
        if self._dialect == "postgres":
            return await self._pg.execute(sql, *params)
        cur = await self._sqlite.execute(sql, params)
        try:
            return None
        finally:
            await cur.close()
            await self._sqlite.commit()

    async def _fetch(self, sql: str, *params):
        sql = _adapt(sql, self._dialect)
        if self._dialect == "postgres":
            return await self._pg.fetch(sql, *params)
        cur = await self._sqlite.execute(sql, params)
        try:
            return await cur.fetchall()
        finally:
            await cur.close()

    async def _fetchone(self, sql: str, *params):
        rows = await self._fetch(sql, *params)
        return rows[0] if rows else None

    # ---------------------------------------------------------- chats

    async def upsert_chat(self, chat_id: int, title: str = "", username: str = "") -> None:
        await self._execute(
            "INSERT INTO chats (chat_id, title, username, joined_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, username = excluded.username",
            int(chat_id), str(title or "")[:255], str(username or "")[:255], int(time.time()),
        )

    async def get_chats(self) -> list[dict]:
        rows = await self._fetch("SELECT * FROM chats ORDER BY title")
        return [dict(r) for r in rows]

    async def get_chat(self, chat_id: int) -> dict | None:
        row = await self._fetchone("SELECT * FROM chats WHERE chat_id = ?", int(chat_id))
        return dict(row) if row else None

    async def set_chat_enabled(self, chat_id: int, enabled: bool) -> None:
        await self._execute("UPDATE chats SET enabled = ? WHERE chat_id = ?", int(enabled), int(chat_id))

    async def remove_chat(self, chat_id: int) -> None:
        await self._execute("DELETE FROM chats WHERE chat_id = ?", int(chat_id))
        await self._execute("DELETE FROM rules WHERE chat_id = ?", int(chat_id))
        await self._execute("DELETE FROM warnings WHERE chat_id = ?", int(chat_id))
        await self._execute("DELETE FROM settings WHERE chat_id = ?", int(chat_id))

    # ---------------------------------------------------------- rules

    async def add_rule(self, chat_id: int, trigger_type: str, trigger_value: str | None,
                       action: str, duration: int | None) -> int:
        params = (int(chat_id), trigger_type, trigger_value, action, duration, int(time.time()))
        if self._dialect == "postgres":
            row = await self._pg.fetchrow(
                _adapt(
                    "INSERT INTO rules (chat_id, trigger_type, trigger_value, action, duration, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                    "postgres",
                ),
                *params,
            )
            return int(row["id"])
        cur = await self._sqlite.execute(
            "INSERT INTO rules (chat_id, trigger_type, trigger_value, action, duration, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            params,
        )
        rid = int(cur.lastrowid)
        await cur.close()
        await self._sqlite.commit()
        return rid

    async def get_rules(self, chat_id: int) -> list[dict]:
        rows = await self._fetch("SELECT * FROM rules WHERE chat_id = ? ORDER BY id", int(chat_id))
        return [dict(r) for r in rows]

    async def get_rule(self, rule_id: int) -> dict | None:
        row = await self._fetchone("SELECT * FROM rules WHERE id = ?", int(rule_id))
        return dict(row) if row else None

    async def delete_rule(self, rule_id: int) -> None:
        await self._execute("DELETE FROM rules WHERE id = ?", int(rule_id))

    async def clear_rules(self, chat_id: int) -> None:
        await self._execute("DELETE FROM rules WHERE chat_id = ?", int(chat_id))

    # ---------------------------------------------------------- warnings

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        await self._execute(
            "INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = warnings.count + 1",
            int(chat_id), int(user_id),
        )
        row = await self._fetchone(
            "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", int(chat_id), int(user_id)
        )
        return int(row["count"]) if row else 1

    async def get_warnings(self, chat_id: int, user_id: int) -> int:
        row = await self._fetchone(
            "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", int(chat_id), int(user_id)
        )
        return int(row["count"]) if row else 0

    async def reset_warnings(self, chat_id: int, user_id: int | None = None) -> None:
        if user_id is not None:
            await self._execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", int(chat_id), int(user_id))
        else:
            await self._execute("DELETE FROM warnings WHERE chat_id = ?", int(chat_id))

    # ---------------------------------------------------------- settings

    async def get_settings(self, chat_id: int) -> dict:
        row = await self._fetchone("SELECT * FROM settings WHERE chat_id = ?", int(chat_id))
        if row:
            return dict(row)
        s = dict(DEFAULT_SETTINGS)
        s["chat_id"] = int(chat_id)
        return s

    async def update_setting(self, chat_id: int, key: str, value: int) -> None:
        if key not in VALID_SETTING_KEYS:
            return
        await self._execute(
            f"INSERT INTO settings (chat_id, {key}) VALUES (?, ?) "
            f"ON CONFLICT(chat_id) DO UPDATE SET {key} = excluded.{key}",
            int(chat_id), int(value),
        )

    async def close(self) -> None:
        if self._dialect == "postgres" and self._pg is not None:
            await self._pg.close()
        if self._dialect == "sqlite" and self._sqlite is not None:
            await self._sqlite.close()
