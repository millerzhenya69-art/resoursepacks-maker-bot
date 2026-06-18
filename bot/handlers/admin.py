"""
Полноценная админ-панель (только для ADMIN_ID / owner).

Возможности:
  /admin                — главная панель
  /addgens <id> <n>     — выдать обычные генерации
  /addai <id> <n>       — выдать ИИ-генерации
  /ban <id>             — забанить пользователя
  /unban <id>           — разбанить
  /broadcast <текст>    — рассылка всем пользователям
  /users                — список последних пользователей (real-time)
  /payments             — сводка по платежам
  /gemini               — проверить статус Gemini API

Все команды работают только от ADMIN_ID.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import ADMIN_ID, GEMINI_API_KEY
from bot.database import get_stats, add_generations, get_user
from bot.database.models import DB_PATH
from bot.services.message_manager import delete_user_message, send_clean

logger = logging.getLogger(__name__)

router = Router()


# ── Состояния для рассылки ────────────────────────────────

class AdminStates(StatesGroup):
    broadcast_text    = State()   # ввод текста рассылки
    broadcast_confirm = State()   # подтверждение рассылки


# ── Проверка прав ─────────────────────────────────────────

def is_owner(user_id: int) -> bool:
    return user_id == ADMIN_ID


def _require_owner(func):
    """Декоратор: молча игнорирует если не owner."""
    async def wrapper(message: Message, *args, **kwargs):
        if not is_owner(message.from_user.id):
            return
        return await func(message, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ── Главная панель ────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    stats = await get_stats()
    gemini_status = await _check_gemini_quick()

    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        f"👤 Пользователей: <b>{stats['users']}</b>\n"
        f"🎨 Генераций создано: <b>{stats['generations']}</b>\n"
        f"💳 Успешных платежей: <b>{stats['payments']}</b>\n"
        f"🤖 Gemini: {gemini_status}\n\n"
        "<b>Команды:</b>\n"
        "/addgens <code>id</code> <code>n</code> — обычные генерации\n"
        "/addai <code>id</code> <code>n</code>   — ИИ-генерации\n"
        "/ban <code>id</code>    — забанить\n"
        "/unban <code>id</code>  — разбанить\n"
        "/broadcast <code>текст</code> — рассылка\n"
        "/users    — список пользователей\n"
        "/payments — сводка платежей\n"
        "/gemini   — статус Gemini API"
    )
    await bot.send_message(
        message.chat.id, text,
        parse_mode="HTML",
        reply_markup=_admin_keyboard(),
    )


def _admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
        InlineKeyboardButton(text="💳 Платежи",       callback_data="adm_payments"),
    )
    builder.row(
        InlineKeyboardButton(text="🤖 Gemini",        callback_data="adm_gemini"),
        InlineKeyboardButton(text="📊 Статистика",    callback_data="adm_stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📣 Рассылка",      callback_data="adm_broadcast"),
    )
    return builder.as_markup()


# ── Callback-кнопки панели ────────────────────────────────

@router.callback_query(F.data == "adm_stats")
async def adm_stats(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()
    stats = await get_stats()
    db_stats = await _get_db_stats()
    text = (
        "📊 <b>Статистика (real-time)</b>\n\n"
        f"👤 Всего пользователей: <b>{stats['users']}</b>\n"
        f"🆕 За последние 24ч: <b>{db_stats['new_24h']}</b>\n"
        f"🚫 Забанено: <b>{db_stats['banned']}</b>\n\n"
        f"🎨 Генераций создано: <b>{stats['generations']}</b>\n"
        f"🤖 ИИ-генераций (всего): <b>{db_stats['ai_total']}</b>\n\n"
        f"💳 Платежей успешных: <b>{stats['payments']}</b>\n"
        f"⏳ Ожидающих: <b>{db_stats['pending_payments']}</b>\n"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=_back_keyboard("adm_main"))


@router.callback_query(F.data == "adm_users")
async def adm_users(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()
    users = await _get_recent_users(limit=20)
    if not users:
        await call.message.edit_text("Пользователей пока нет.", reply_markup=_back_keyboard("adm_main"))
        return

    lines = ["👥 <b>Последние 20 пользователей</b>\n"]
    for u in users:
        ban_mark = " 🚫" if u["is_banned"] else ""
        username = f"@{u['username']}" if u["username"] else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {username}{ban_mark}\n"
            f"  🎨{u['generations']} 🤖{u['ai_generations']} 📊{u['total_generated']}"
            f" | {_fmt_date(u['created_at'])}"
        )

    await call.message.edit_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_back_keyboard("adm_main"),
    )


@router.callback_query(F.data == "adm_payments")
async def adm_payments(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()
    pays = await _get_recent_payments(limit=15)
    if not pays:
        await call.message.edit_text("Платежей пока нет.", reply_markup=_back_keyboard("adm_main"))
        return

    lines = ["💳 <b>Последние 15 платежей</b>\n"]
    for p in pays:
        status_icon = "✅" if p["status"] == "paid" else "⏳"
        lines.append(
            f"{status_icon} <code>{p['user_id']}</code> | {p['method']} | "
            f"{p['tariff'] or '—'} | {p['gens_added']}ген | "
            f"{_fmt_date(p['created_at'])}"
        )

    total_paid = await _get_total_paid()
    lines.append(f"\n💰 <b>Всего оплачено:</b> ~{total_paid} ₽")

    await call.message.edit_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_back_keyboard("adm_main"),
    )


@router.callback_query(F.data == "adm_gemini")
async def adm_gemini(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer("Проверяю Gemini...")
    result = await _check_gemini_full()
    await call.message.edit_text(result, parse_mode="HTML", reply_markup=_back_keyboard("adm_main"))


@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminStates.broadcast_text)
    await call.message.edit_text(
        "📣 <b>Рассылка</b>\n\n"
        "Введи текст сообщения (поддерживается HTML).\n"
        "Для отмены: /cancel",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )


@router.callback_query(F.data == "adm_main")
async def adm_main(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()
    stats = await get_stats()
    gemini_status = await _check_gemini_quick()
    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        f"👤 Пользователей: <b>{stats['users']}</b>\n"
        f"🎨 Генераций создано: <b>{stats['generations']}</b>\n"
        f"💳 Успешных платежей: <b>{stats['payments']}</b>\n"
        f"🤖 Gemini: {gemini_status}\n\n"
        "Выбери раздел:"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=_admin_keyboard())


# ── /addgens ─────────────────────────────────────────────

@router.message(Command("addgens"))
async def cmd_addgens(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await bot.send_message(
            message.chat.id,
            "Использование: /addgens <code>user_id</code> <code>кол-во</code>",
            parse_mode="HTML",
        )
        return

    user_id, amount = int(parts[1]), int(parts[2])
    await add_generations(user_id, amount, ai=False)
    ud = await get_user(user_id)
    bal = ud["generations"] if ud else "?"
    await bot.send_message(
        message.chat.id,
        f"✅ Пользователю <code>{user_id}</code> добавлено <b>{amount}</b> обычных генераций.\n"
        f"Баланс: <b>{bal}</b>",
        parse_mode="HTML",
    )


# ── /addai ────────────────────────────────────────────────

@router.message(Command("addai"))
async def cmd_addai(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await bot.send_message(
            message.chat.id,
            "Использование: /addai <code>user_id</code> <code>кол-во</code>",
            parse_mode="HTML",
        )
        return

    user_id, amount = int(parts[1]), int(parts[2])
    await add_generations(user_id, amount, ai=True)
    ud = await get_user(user_id)
    bal = ud["ai_generations"] if ud else "?"
    await bot.send_message(
        message.chat.id,
        f"✅ Пользователю <code>{user_id}</code> добавлено <b>{amount}</b> ИИ-генераций.\n"
        f"ИИ-баланс: <b>{bal}</b>",
        parse_mode="HTML",
    )


# ── /ban / /unban ─────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await bot.send_message(
            message.chat.id,
            "Использование: /ban <code>user_id</code>",
            parse_mode="HTML",
        )
        return

    user_id = int(parts[1])
    if user_id == ADMIN_ID:
        await bot.send_message(message.chat.id, "❌ Нельзя забанить себя.")
        return

    await _set_ban(user_id, banned=True)
    await bot.send_message(
        message.chat.id,
        f"🚫 Пользователь <code>{user_id}</code> <b>забанен</b>.",
        parse_mode="HTML",
    )
    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            "🚫 Ваш аккаунт заблокирован администратором.",
        )
    except Exception:
        pass


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await bot.send_message(
            message.chat.id,
            "Использование: /unban <code>user_id</code>",
            parse_mode="HTML",
        )
        return

    user_id = int(parts[1])
    await _set_ban(user_id, banned=False)
    await bot.send_message(
        message.chat.id,
        f"✅ Пользователь <code>{user_id}</code> <b>разбанен</b>.",
        parse_mode="HTML",
    )


# ── /broadcast ────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    # Поддерживаем два формата:
    # /broadcast <текст>    — сразу задаём текст
    # /broadcast            — переходим в FSM
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        text = parts[1].strip()
        await state.update_data(broadcast_text=text)
        await state.set_state(AdminStates.broadcast_confirm)
        count = await _count_all_users()
        await bot.send_message(
            message.chat.id,
            f"📣 <b>Предпросмотр рассылки</b>\n\n{text}\n\n"
            f"👥 Получат: <b>{count}</b> пользователей\n\n"
            "Подтвердить?",
            parse_mode="HTML",
            reply_markup=_confirm_broadcast_keyboard(),
        )
        return

    await state.set_state(AdminStates.broadcast_text)
    await bot.send_message(
        message.chat.id,
        "📣 <b>Рассылка</b>\n\nВведи текст сообщения (HTML разрешён):",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )


@router.message(AdminStates.broadcast_text, F.text)
async def broadcast_receive_text(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return
    await delete_user_message(message)

    text = message.text.strip()
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminStates.broadcast_confirm)

    count = await _count_all_users()
    await bot.send_message(
        message.chat.id,
        f"📣 <b>Предпросмотр рассылки</b>\n\n{text}\n\n"
        f"👥 Получат: <b>{count}</b> пользователей\n\n"
        "Подтвердить отправку?",
        parse_mode="HTML",
        reply_markup=_confirm_broadcast_keyboard(),
    )


@router.callback_query(AdminStates.broadcast_confirm, F.data == "broadcast_confirm")
async def broadcast_do_send(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer()

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()

    await call.message.edit_text(
        "📣 <b>Рассылка запущена...</b>\n\nПодожди, это может занять время.",
        parse_mode="HTML",
    )

    sent, failed, blocked = await _do_broadcast(bot, text)

    await bot.send_message(
        call.message.chat.id,
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.answer("Отменено")
    await state.clear()
    await call.message.edit_text("❌ Рассылка отменена.")


# ── /users ────────────────────────────────────────────────

@router.message(Command("users"))
async def cmd_users(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    users = await _get_recent_users(limit=20)
    if not users:
        await bot.send_message(message.chat.id, "Пользователей пока нет.")
        return

    lines = [f"👥 <b>Пользователи (последние 20 из {await _count_all_users()})</b>\n"]
    for u in users:
        ban_mark = " 🚫" if u["is_banned"] else ""
        username = f"@{u['username']}" if u["username"] else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {username}{ban_mark}\n"
            f"  🎨{u['generations']} 🤖{u['ai_generations']} 📊{u['total_generated']}"
            f" | {_fmt_date(u['created_at'])}"
        )

    await bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML",
    )


# ── /payments ─────────────────────────────────────────────

@router.message(Command("payments"))
async def cmd_payments(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    pays = await _get_recent_payments(limit=20)
    if not pays:
        await bot.send_message(message.chat.id, "Платежей пока нет.")
        return

    lines = ["💳 <b>Платежи (последние 20)</b>\n"]
    for p in pays:
        status_icon = "✅" if p["status"] == "paid" else "⏳"
        lines.append(
            f"{status_icon} <code>{p['user_id']}</code> | {p['method']} | "
            f"{p['tariff'] or '—'} | {p['gens_added']}ген | "
            f"~{p.get('amount', 0):.0f}₽ | {_fmt_date(p['created_at'])}"
        )

    total = await _get_total_paid()
    lines.append(f"\n💰 <b>Итого оплачено:</b> ~{total:.0f} ₽")

    await bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML",
    )


# ── /gemini ───────────────────────────────────────────────

@router.message(Command("gemini"))
async def cmd_gemini(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_owner(message.from_user.id):
        return

    wait_msg = await bot.send_message(message.chat.id, "🤖 Проверяю Gemini API...")
    result = await _check_gemini_full()
    await bot.delete_message(message.chat.id, wait_msg.message_id)
    await bot.send_message(message.chat.id, result, parse_mode="HTML")


# ── /cancel (для FSM) ─────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    current = await state.get_state()
    if current:
        await state.clear()
        await bot.send_message(message.chat.id, "❌ Отменено.")


# ── Вспомогательные функции ───────────────────────────────

async def _get_recent_users(limit: int = 20) -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, username, full_name, generations, ai_generations, "
            "total_generated, is_banned, created_at "
            "FROM users ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def _get_recent_payments(limit: int = 20) -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, method, tariff, amount, gens_added, status, created_at "
            "FROM payments ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def _count_all_users() -> int:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return row[0] if row else 0


async def _get_db_stats() -> dict:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE created_at >= datetime('now', '-1 day')"
        )
        new_24h = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM generations WHERE mode = 'ai' AND status = 'done'"
        )
        ai_total = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM payments WHERE status = 'pending'"
        )
        pending = (await cur.fetchone())[0]

    return {
        "new_24h": new_24h,
        "banned": banned,
        "ai_total": ai_total,
        "pending_payments": pending,
    }


async def _get_total_paid() -> float:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'"
        )
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0


async def _set_ban(user_id: int, banned: bool) -> None:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (1 if banned else 0, user_id)
        )
        await db.commit()


async def _get_all_user_ids() -> list[int]:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id FROM users WHERE is_banned = 0 ORDER BY created_at"
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def _do_broadcast(bot: Bot, text: str) -> tuple[int, int, int]:
    """Рассылает сообщение всем незабаненным пользователям."""
    user_ids = await _get_all_user_ids()
    sent = failed = blocked = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "chat not found" in err:
                blocked += 1
            else:
                failed += 1
                logger.warning(f"Broadcast to {uid} failed: {e}")
        # Небольшая задержка чтобы не получить flood control
        await asyncio.sleep(0.05)

    logger.info(f"Broadcast done: sent={sent} blocked={blocked} failed={failed}")
    return sent, failed, blocked


async def _check_gemini_quick() -> str:
    """Быстрая проверка — просто наличие ключа."""
    if not GEMINI_API_KEY:
        return "❌ Ключ не задан"
    return "✅ Ключ задан"


async def _check_gemini_full() -> str:
    """Полная проверка всех моделей Gemini."""
    if not GEMINI_API_KEY:
        return "❌ <b>GEMINI_API_KEY не задан</b> в переменных окружения."

    MODELS = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    TEST_PAYLOAD = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with just: OK"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }

    lines = ["🤖 <b>Статус Gemini API</b>\n"]
    any_ok = False

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=10)
    ) as session:
        for model in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            try:
                async with session.post(url, json=TEST_PAYLOAD) as r:
                    if r.status == 200:
                        lines.append(f"✅ <code>{model}</code> — работает")
                        any_ok = True
                    elif r.status == 429:
                        lines.append(f"⏳ <code>{model}</code> — квота (429)")
                        any_ok = True  # ключ рабочий, просто лимит
                    elif r.status == 403:
                        lines.append(f"🔑 <code>{model}</code> — нет доступа (403)")
                    elif r.status == 404:
                        lines.append(f"❌ <code>{model}</code> — не найдена (404)")
                    else:
                        lines.append(f"? <code>{model}</code> — HTTP {r.status}")
            except asyncio.TimeoutError:
                lines.append(f"⏰ <code>{model}</code> — таймаут")
            except Exception as e:
                lines.append(f"❌ <code>{model}</code> — {str(e)[:40]}")

    if any_ok:
        lines.append("\n✅ <b>Как минимум одна модель работает</b>")
    else:
        lines.append("\n❌ <b>Ни одна модель не отвечает</b>")

    return "\n".join(lines)


def _fmt_date(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "—"
    # Обрезаем до даты и времени без секунд
    return str(dt_str)[:16] if len(str(dt_str)) > 10 else str(dt_str)


# ── Клавиатуры ────────────────────────────────────────────

def _back_keyboard(cb: str = "adm_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=cb))
    return builder.as_markup()


def _cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"))
    return builder.as_markup()


def _confirm_broadcast_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить всем", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отмена",          callback_data="broadcast_cancel"),
    )
    return builder.as_markup()
