import aiosqlite
import os
from bot.config import BASE_DIR, DATABASE_URL

DB_PATH = os.path.join(BASE_DIR, "bot.db")


async def get_db() -> aiosqlite.Connection:
    """Возвращает соединение с БД."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Создаёт таблицы при первом запуске."""
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
            method      TEXT    NOT NULL,   -- 'stars' | 'cryptobot' | 'donatepay'
            tariff      TEXT,               -- 'start' | 'basic' | 'pro' | 'ai_pack' | 'custom'
            amount      REAL    NOT NULL,   -- сумма в рублях
            stars       INTEGER DEFAULT 0,
            gens_added  INTEGER NOT NULL,
            status      TEXT    DEFAULT 'pending',  -- 'pending' | 'paid' | 'failed'
            payload     TEXT,               -- внешний ID платежа
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS generations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            mode        TEXT    NOT NULL,   -- 'template' | 'custom' | 'ai'
            version     TEXT    NOT NULL,   -- '1.21.4' | '1.21.8' | '1.21.11'
            params      TEXT,              -- JSON параметры
            status      TEXT    DEFAULT 'pending',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code);
        CREATE INDEX IF NOT EXISTS idx_payments_user  ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_gens_user      ON generations(user_id);
        """)
        await db.commit()


# ── CRUD ──────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str, full_name: str,
                              ref_code: str | None = None) -> dict:
    """Получает или создаёт пользователя. Начисляет бонус рефереру."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        user = await row.fetchone()

        if user:
            await db.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP, username = ?, full_name = ? WHERE user_id = ?",
                (username, full_name, user_id)
            )
            await db.commit()
            return dict(user)

        # Генерируем уникальный реферальный код
        import hashlib, time
        my_ref = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()

        referred_by = None
        if ref_code:
            r = await db.execute(
                "SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)
            )
            referrer = await r.fetchone()
            if referrer and referrer["user_id"] != user_id:
                referred_by = referrer["user_id"]
                # Бонус рефереру
                await db.execute(
                    "UPDATE users SET generations = generations + 2 WHERE user_id = ?",
                    (referred_by,)
                )

        await db.execute(
            """INSERT INTO users (user_id, username, full_name, referral_code, referred_by)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, full_name, my_ref, referred_by)
        )
        await db.commit()

        row2 = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(await row2.fetchone())


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        r = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await r.fetchone()
        return dict(row) if row else None


async def deduct_generation(user_id: int, ai: bool = False) -> bool:
    """Списывает одну генерацию. Возвращает False если недостаточно."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        r = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await r.fetchone()
        if not user:
            return False

        col = "ai_generations" if ai else "generations"
        if user[col] < 1:
            return False

        await db.execute(
            f"UPDATE users SET {col} = {col} - 1, total_generated = total_generated + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        return True


async def add_generations(user_id: int, amount: int, ai: bool = False) -> None:
    col = "ai_generations" if ai else "generations"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()


async def get_stats() -> dict:
    """Статистика для админа."""
    async with aiosqlite.connect(DB_PATH) as db:
        r1 = await db.execute("SELECT COUNT(*) FROM users")
        r2 = await db.execute("SELECT COUNT(*) FROM generations WHERE status = 'done'")
        r3 = await db.execute("SELECT COUNT(*) FROM payments WHERE status = 'paid'")
        total_users = (await r1.fetchone())[0]
        total_gens  = (await r2.fetchone())[0]
        total_pays  = (await r3.fetchone())[0]
    return {"users": total_users, "generations": total_gens, "payments": total_pays}
