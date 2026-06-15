"""
База данных — поддержка SQLite (локально) и PostgreSQL (прод/Render).

Автоматически определяет тип по DATABASE_URL:
  - Пусто или sqlite → aiosqlite (bot.db)
  - postgresql://... → asyncpg
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Optional

from bot.config import BASE_DIR, DATABASE_URL

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(BASE_DIR, "bot.db")

# Определяем бэкенд один раз при импорте
_USE_PG = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql"))


# ── Универсальный контекст-менеджер ───────────────────────

class _DB:
    """
    Тонкая обёртка, которая даёт одинаковый API для SQLite и PostgreSQL.
    Использует ? для SQLite и $1,$2,... для asyncpg.
    """

    def __init__(self):
        self._conn = None

    async def __aenter__(self):
        if _USE_PG:
            import asyncpg
            self._conn = await asyncpg.connect(DATABASE_URL)
        else:
            import aiosqlite
            self._conn = await aiosqlite.connect(DB_PATH)
            self._conn.row_factory = aiosqlite.Row
        return self

    async def __aexit__(self, *_):
        if self._conn:
            await self._conn.close()

    def _sql(self, query: str) -> str:
        """Конвертирует ? → $1,$2,... для PostgreSQL."""
        if not _USE_PG:
            return query
        i = 0
        result = []
        for ch in query:
            if ch == "?":
                i += 1
                result.append(f"${i}")
            else:
                result.append(ch)
        return "".join(result)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        q = self._sql(query)
        if _USE_PG:
            row = await self._conn.fetchrow(q, *params)
            return dict(row) if row else None
        else:
            cur = await self._conn.execute(q, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchval(self, query: str, params: tuple = ()):
        q = self._sql(query)
        if _USE_PG:
            return await self._conn.fetchval(q, *params)
        else:
            cur = await self._conn.execute(q, params)
            row = await cur.fetchone()
            return row[0] if row else None

    async def execute(self, query: str, params: tuple = ()):
        q = self._sql(query)
        if _USE_PG:
            await self._conn.execute(q, *params)
        else:
            await self._conn.execute(q, params)

    async def commit(self):
        if not _USE_PG:
            await self._conn.commit()
        # asyncpg — autocommit по умолчанию


# ── Инициализация схемы ───────────────────────────────────

async def init_db() -> None:
    """Создаёт таблицы при первом запуске."""
    if _USE_PG:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         BIGINT PRIMARY KEY,
                username        TEXT,
                full_name       TEXT,
                generations     INTEGER  DEFAULT 3,
                ai_generations  INTEGER  DEFAULT 0,
                total_generated INTEGER  DEFAULT 0,
                referral_code   TEXT     UNIQUE,
                referred_by     BIGINT,
                is_banned       INTEGER  DEFAULT 0,
                created_at      TIMESTAMP DEFAULT NOW(),
                last_active     TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS payments (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                method      TEXT   NOT NULL,
                tariff      TEXT,
                amount      REAL   NOT NULL,
                stars       INTEGER DEFAULT 0,
                gens_added  INTEGER NOT NULL,
                status      TEXT    DEFAULT 'pending',
                payload     TEXT,
                created_at  TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS generations (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                mode        TEXT   NOT NULL,
                version     TEXT   NOT NULL,
                params      TEXT,
                status      TEXT   DEFAULT 'pending',
                created_at  TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code);
            CREATE INDEX IF NOT EXISTS idx_payments_user  ON payments(user_id);
            CREATE INDEX IF NOT EXISTS idx_gens_user      ON generations(user_id);
            """)
            logger.info("PostgreSQL schema ready")
        finally:
            await conn.close()
    else:
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                full_name       TEXT,
                generations     INTEGER  DEFAULT 3,
                ai_generations  INTEGER  DEFAULT 0,
                total_generated INTEGER  DEFAULT 0,
                referral_code   TEXT     UNIQUE,
                referred_by     INTEGER,
                is_banned       INTEGER  DEFAULT 0,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_active     DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                method      TEXT    NOT NULL,
                tariff      TEXT,
                amount      REAL    NOT NULL,
                stars       INTEGER DEFAULT 0,
                gens_added  INTEGER NOT NULL,
                status      TEXT    DEFAULT 'pending',
                payload     TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS generations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                mode        TEXT    NOT NULL,
                version     TEXT    NOT NULL,
                params      TEXT,
                status      TEXT    DEFAULT 'pending',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code);
            CREATE INDEX IF NOT EXISTS idx_payments_user  ON payments(user_id);
            CREATE INDEX IF NOT EXISTS idx_gens_user      ON generations(user_id);
            """)
            await db.commit()
            logger.info("SQLite schema ready")


# ── CRUD ──────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str, full_name: str,
                              ref_code: str | None = None) -> dict:
    async with _DB() as db:
        user = await db.fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        if user:
            await db.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP, "
                "username = ?, full_name = ? WHERE user_id = ?",
                (username, full_name, user_id)
            )
            await db.commit()
            return user

        my_ref = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()

        referred_by = None
        if ref_code:
            referrer = await db.fetchone(
                "SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)
            )
            if referrer and referrer["user_id"] != user_id:
                referred_by = referrer["user_id"]
                await db.execute(
                    "UPDATE users SET generations = generations + 2 WHERE user_id = ?",
                    (referred_by,)
                )

        await db.execute(
            "INSERT INTO users (user_id, username, full_name, referral_code, referred_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, my_ref, referred_by)
        )
        await db.commit()

        return await db.fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )


async def get_user(user_id: int) -> dict | None:
    async with _DB() as db:
        return await db.fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )


async def deduct_generation(user_id: int, ai: bool = False) -> bool:
    async with _DB() as db:
        user = await db.fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        if not user:
            return False
        col = "ai_generations" if ai else "generations"
        if user[col] < 1:
            return False
        await db.execute(
            f"UPDATE users SET {col} = {col} - 1, "
            f"total_generated = total_generated + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        return True


async def add_generations(user_id: int, amount: int, ai: bool = False) -> None:
    col = "ai_generations" if ai else "generations"
    async with _DB() as db:
        await db.execute(
            f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()


async def get_stats() -> dict:
    async with _DB() as db:
        users = await db.fetchval("SELECT COUNT(*) FROM users") or 0
        gens  = await db.fetchval(
            "SELECT COUNT(*) FROM generations WHERE status = 'done'"
        ) or 0
        pays  = await db.fetchval(
            "SELECT COUNT(*) FROM payments WHERE status = 'paid'"
        ) or 0
    return {"users": users, "generations": gens, "payments": pays}
