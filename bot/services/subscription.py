"""
Проверка обязательной подписки на каналы и ботов.

Логика:
- Обычные каналы (@unkonyy, @AI_Elyon) — проверяем через get_chat_member
- Бот (@Elyon_by_unkony_bot) — проверяем через БД (факт запуска /start у того бота)
  Пометку ставит сам @Elyon_by_unkony_bot при старте, либо мы принимаем
  на веру после нажатия кнопки (честная система — Telegram не даёт другого способа).

ИСПРАВЛЕНО: mark_bot_started / _check_bot_started переведены с прямого
aiosqlite.connect() на универсальный _DB (PostgreSQL + SQLite совместимость).
Также таблица bot_starts теперь создаётся через CREATE TABLE с правильным
синтаксисом для обоих бэкендов вместо SQLite-only executescript.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from bot.config import REQUIRED_CHANNELS
from bot.database.models import _DB

# username ботов (не каналов) — для них get_chat_member не работает
BOT_USERNAMES: set[str] = {"Elyon_by_unkony_bot"}

_table_ready = False


async def _ensure_bot_starts_table():
    """Создаёт таблицу bot_starts один раз при первом обращении."""
    global _table_ready
    if _table_ready:
        return
    async with _DB() as db:
        if _DB._USE_PG_FLAG():
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_starts (
                    user_id      BIGINT NOT NULL,
                    bot_username TEXT   NOT NULL,
                    PRIMARY KEY (user_id, bot_username)
                )
            """)
        else:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_starts (
                    user_id      INTEGER NOT NULL,
                    bot_username TEXT    NOT NULL,
                    PRIMARY KEY (user_id, bot_username)
                )
            """)
        await db.commit()
    _table_ready = True


async def check_subscriptions(bot: Bot, user_id: int) -> list[dict]:
    """
    Проверяет подписку на все обязательные каналы/ботов.
    Возвращает список тех, на кого пользователь НЕ подписан.
    """
    not_subscribed = []
    for channel in REQUIRED_CHANNELS:
        username = channel["username"]

        if username in BOT_USERNAMES:
            started = await _check_bot_started(user_id, username)
            if not started:
                not_subscribed.append(channel)
        else:
            subscribed = await _is_channel_member(bot, user_id, username)
            if not subscribed:
                not_subscribed.append(channel)

    return not_subscribed


async def mark_bot_started(user_id: int, bot_username: str) -> None:
    """
    Вызывается когда пользователь нажимает кнопку 'Я подписался'.
    Помечаем что он запустил бота (доверяем на слово — иначе никак).
    """
    await _ensure_bot_starts_table()
    async with _DB() as db:
        # INSERT OR IGNORE — SQLite-синтаксис; для PG нужен ON CONFLICT DO NOTHING
        if _DB._USE_PG_FLAG():
            await db.execute(
                "INSERT INTO bot_starts (user_id, bot_username) VALUES (?, ?) "
                "ON CONFLICT (user_id, bot_username) DO NOTHING",
                (user_id, bot_username)
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO bot_starts (user_id, bot_username) VALUES (?, ?)",
                (user_id, bot_username)
            )
        await db.commit()


async def mark_all_bots_started(user_id: int) -> None:
    """Помечает все требуемые боты как запущенные для данного пользователя."""
    for username in BOT_USERNAMES:
        await mark_bot_started(user_id, username)


async def _check_bot_started(user_id: int, bot_username: str) -> bool:
    """Проверяет флаг в БД."""
    try:
        await _ensure_bot_starts_table()
        async with _DB() as db:
            row = await db.fetchone(
                "SELECT 1 FROM bot_starts WHERE user_id = ? AND bot_username = ?",
                (user_id, bot_username)
            )
            return row is not None
    except Exception:
        return False


async def _is_channel_member(bot: Bot, user_id: int, channel_username: str) -> bool:
    """Проверяет подписку на канал через Telegram API."""
    try:
        member = await bot.get_chat_member(
            chat_id=f"@{channel_username}", user_id=user_id
        )
        return member.status not in ("left", "kicked", "banned")
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "chat not found" in err or "bot is not a member" in err or "user not found" in err:
            return True
        return False
    except Exception:
        return True
