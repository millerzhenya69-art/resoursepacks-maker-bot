"""
Патч для admin.py — исправлен /gemini (ValidationError в edit_message_text).
"""
from __future__ import annotations

import asyncio
import logging

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
from bot.database.models import _DB

logger = logging.getLogger(__name__)
router = Router()


class AdminStates(StatesGroup):
    broadcast_text    = State()
    broadcast_confirm = State()


def is_owner(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def _try_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


# ── /admin ────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id):
        return
    stats   = await get_stats()
    gstatus = await _check_gemini_quick()
    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        f"👤 Пользователей: <b>{stats['users']}</b>\n"
        f"🎨 Генераций: <b>{stats['generations']}</b>\n"
        f"💳 Платежей: <b>{stats['payments']}</b>\n"
        f"🤖 Gemini: {gstatus}\n\n"
        "<b>Команды:</b>\n"
        "/addgens <code>id n</code> — обычные генерации\n"
        "/addai <code>id n</code>   — ИИ-генерации\n"
        "/ban <code>id</code>       — забанить\n"
        "/unban <code>id</code>     — разбанить\n"
        "/broadcast <code>текст</code> — рассылка\n"
        "/users    — список пользователей\n"
        "/payments — сводка платежей\n"
        "/gemini   — статус Gemini API"
    )
    await bot.send_message(message.chat.id, text, parse_mode="HTML",
                           reply_markup=_admin_kb())


def _admin_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
        InlineKeyboardButton(text="💳 Платежи",       callback_data="adm_payments"),
    )
    b.row(
        InlineKeyboardButton(text="🤖 Gemini",        callback_data="adm_gemini"),
        InlineKeyboardButton(text="📊 Статистика",    callback_data="adm_stats"),
    )
    b.row(InlineKeyboardButton(text="📣 Рассылка", callback_data="adm_broadcast"))
    return b.as_markup()


# ── Callbacks ─────────────────────────────────────────────

@router.callback_query(F.data == "adm_main")
async def adm_main(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    stats   = await get_stats()
    gstatus = await _check_gemini_quick()
    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        f"👤 Пользователей: <b>{stats['users']}</b>\n"
        f"🎨 Генераций: <b>{stats['generations']}</b>\n"
        f"💳 Платежей: <b>{stats['payments']}</b>\n"
        f"🤖 Gemini: {gstatus}\n\nВыбери раздел:"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=_admin_kb())


@router.callback_query(F.data == "adm_stats")
async def adm_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    stats = await get_stats()
    ex    = await _get_extra_stats()
    text = (
        "📊 <b>Статистика (real-time)</b>\n\n"
        f"👤 Всего: <b>{stats['users']}</b>\n"
        f"🆕 За 24ч: <b>{ex['new_24h']}</b>\n"
        f"🚫 Забанено: <b>{ex['banned']}</b>\n\n"
        f"🎨 Генераций: <b>{stats['generations']}</b>\n"
        f"🤖 ИИ-генераций: <b>{ex['ai_done']}</b>\n\n"
        f"💳 Платежей: <b>{stats['payments']}</b>\n"
        f"⏳ Ожидающих: <b>{ex['pending_payments']}</b>\n"
        f"💰 Суммарно: <b>~{ex['total_paid']:.0f} ₽</b>"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=_back_kb())


@router.callback_query(F.data == "adm_users")
async def adm_users_cb(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    users = await _get_recent_users(20)
    total = await _count_users()
    lines = [f"👥 <b>Последние 20 из {total}</b>\n"]
    for u in users:
        ban   = " 🚫" if u.get("is_banned") else ""
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {uname}{ban}\n"
            f"  🎨{u['generations']} 🤖{u['ai_generations']} 📊{u['total_generated']}"
            f"  {_fmt_dt(u.get('created_at'))}"
        )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=_back_kb())


@router.callback_query(F.data == "adm_payments")
async def adm_payments_cb(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    pays  = await _get_recent_payments(15)
    total = await _get_total_paid()
    lines = ["💳 <b>Последние 15 платежей</b>\n"]
    for p in pays:
        icon = "✅" if p.get("status") == "paid" else "⏳"
        lines.append(
            f"{icon} <code>{p['user_id']}</code> | {p.get('method','—')} | "
            f"{p.get('tariff','—')} | {p.get('gens_added',0)}ген | "
            f"~{float(p.get('amount') or 0):.0f}₽ | {_fmt_dt(p.get('created_at'))}"
        )
    lines.append(f"\n💰 <b>Итого:</b> ~{total:.0f} ₽")
    await call.message.edit_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=_back_kb())


@router.callback_query(F.data == "adm_gemini")
async def adm_gemini_cb(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer("Проверяю...")
    result = await _check_gemini_full()
    await call.message.edit_text(result, parse_mode="HTML", reply_markup=_back_kb())


@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.broadcast_text)
    await call.message.edit_text(
        "📣 <b>Рассылка</b>\n\nВведи текст (HTML поддерживается).\n/cancel — отмена",
        parse_mode="HTML", reply_markup=_cancel_kb())


# ── /addgens ─────────────────────────────────────────────

@router.message(Command("addgens"))
async def cmd_addgens(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await bot.send_message(message.chat.id,
            "Использование: /addgens <code>user_id</code> <code>кол-во</code>",
            parse_mode="HTML"); return
    uid, n = int(parts[1]), int(parts[2])
    await add_generations(uid, n, ai=False)
    ud = await get_user(uid)
    await bot.send_message(message.chat.id,
        f"✅ <code>{uid}</code> +<b>{n}</b> обычных. Баланс: <b>{ud['generations'] if ud else '?'}</b>",
        parse_mode="HTML")


# ── /addai ────────────────────────────────────────────────

@router.message(Command("addai"))
async def cmd_addai(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await bot.send_message(message.chat.id,
            "Использование: /addai <code>user_id</code> <code>кол-во</code>",
            parse_mode="HTML"); return
    uid, n = int(parts[1]), int(parts[2])
    await add_generations(uid, n, ai=True)
    ud = await get_user(uid)
    await bot.send_message(message.chat.id,
        f"✅ <code>{uid}</code> +<b>{n}</b> ИИ-генераций. ИИ-баланс: <b>{ud['ai_generations'] if ud else '?'}</b>",
        parse_mode="HTML")


# ── /ban / /unban ─────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await bot.send_message(message.chat.id,
            "Использование: /ban <code>user_id</code>", parse_mode="HTML"); return
    uid = int(parts[1])
    if uid == ADMIN_ID:
        await bot.send_message(message.chat.id, "❌ Нельзя забанить себя."); return
    await _set_ban(uid, True)
    await bot.send_message(message.chat.id,
        f"🚫 <code>{uid}</code> забанен.", parse_mode="HTML")
    try:
        await bot.send_message(uid, "🚫 Ваш аккаунт заблокирован администратором.")
    except Exception:
        pass


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await bot.send_message(message.chat.id,
            "Использование: /unban <code>user_id</code>", parse_mode="HTML"); return
    uid = int(parts[1])
    await _set_ban(uid, False)
    await bot.send_message(message.chat.id,
        f"✅ <code>{uid}</code> разбанен.", parse_mode="HTML")


# ── /broadcast ────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        text  = parts[1].strip()
        count = await _count_users()
        await state.update_data(broadcast_text=text)
        await state.set_state(AdminStates.broadcast_confirm)
        await bot.send_message(message.chat.id,
            f"📣 <b>Предпросмотр</b>\n\n{text}\n\n"
            f"👥 Получат: <b>{count}</b>\nПодтвердить?",
            parse_mode="HTML", reply_markup=_confirm_kb())
        return
    await state.set_state(AdminStates.broadcast_text)
    await bot.send_message(message.chat.id,
        "📣 <b>Рассылка</b>\n\nВведи текст:",
        parse_mode="HTML", reply_markup=_cancel_kb())


@router.message(AdminStates.broadcast_text, F.text)
async def broadcast_recv(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id): return
    await _try_delete(message)
    text  = message.text.strip()
    count = await _count_users()
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminStates.broadcast_confirm)
    await bot.send_message(message.chat.id,
        f"📣 <b>Предпросмотр</b>\n\n{text}\n\n"
        f"👥 Получат: <b>{count}</b>\nПодтвердить?",
        parse_mode="HTML", reply_markup=_confirm_kb())


@router.callback_query(AdminStates.broadcast_confirm, F.data == "broadcast_confirm")
async def broadcast_do(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer()
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    await call.message.edit_text("📣 <b>Рассылка запущена...</b>", parse_mode="HTML")
    sent, failed, blocked = await _do_broadcast(bot, text)
    await bot.send_message(call.message.chat.id,
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали: <b>{blocked}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>",
        parse_mode="HTML")


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.answer("Отменено")
    await state.clear()
    await call.message.edit_text("❌ Рассылка отменена.")


# ── /users ────────────────────────────────────────────────

@router.message(Command("users"))
async def cmd_users(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    users = await _get_recent_users(20)
    total = await _count_users()
    lines = [f"👥 <b>Последние 20 из {total}</b>\n"]
    for u in users:
        ban   = " 🚫" if u.get("is_banned") else ""
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {uname}{ban}\n"
            f"  🎨{u['generations']} 🤖{u['ai_generations']} 📊{u['total_generated']}"
            f"  {_fmt_dt(u.get('created_at'))}"
        )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await bot.send_message(message.chat.id, text, parse_mode="HTML")


# ── /payments ─────────────────────────────────────────────

@router.message(Command("payments"))
async def cmd_payments(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    pays  = await _get_recent_payments(20)
    total = await _get_total_paid()
    lines = ["💳 <b>Последние 20 платежей</b>\n"]
    for p in pays:
        icon = "✅" if p.get("status") == "paid" else "⏳"
        lines.append(
            f"{icon} <code>{p['user_id']}</code> | {p.get('method','—')} | "
            f"{p.get('tariff','—')} | {p.get('gens_added',0)}ген | "
            f"~{float(p.get('amount') or 0):.0f}₽ | {_fmt_dt(p.get('created_at'))}"
        )
    lines.append(f"\n💰 <b>Итого:</b> ~{total:.0f} ₽")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await bot.send_message(message.chat.id, text, parse_mode="HTML")


# ── /gemini — ИСПРАВЛЕНО ──────────────────────────────────
# Старый код: bot.edit_message_text(result, chat_id, msg_id)
# aiogram 3.x: позиционные аргументы (text, chat_id, msg_id) не работают —
# chat_id попадает в business_connection_id (строка, а не int → ValidationError).
# Правильно: использовать m.edit_text() напрямую.

@router.message(Command("gemini"))
async def cmd_gemini(message: Message, bot: Bot):
    await _try_delete(message)
    if not is_owner(message.from_user.id): return
    # Отправляем сообщение-заглушку и редактируем его результатом
    m = await bot.send_message(message.chat.id, "🤖 Проверяю Gemini API...")
    result = await _check_gemini_full()
    # Используем метод объекта Message, а не bot.edit_message_text —
    # это исключает путаницу с позиционными аргументами
    await m.edit_text(result, parse_mode="HTML")


# ── /cancel ───────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot):
    await _try_delete(message)
    if await state.get_state():
        await state.clear()
        await bot.send_message(message.chat.id, "❌ Отменено.")


# ── DB-хелперы ────────────────────────────────────────────

async def _get_recent_users(limit: int) -> list[dict]:
    async with _DB() as db:
        return await db.fetchall(
            "SELECT user_id, username, full_name, generations, ai_generations, "
            "total_generated, is_banned, created_at "
            "FROM users ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )


async def _get_recent_payments(limit: int) -> list[dict]:
    async with _DB() as db:
        return await db.fetchall(
            "SELECT user_id, method, tariff, amount, gens_added, status, created_at "
            "FROM payments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )


async def _count_users() -> int:
    async with _DB() as db:
        return await db.fetchval("SELECT COUNT(*) FROM users") or 0


async def _get_extra_stats() -> dict:
    async with _DB() as db:
        if _DB._USE_PG_FLAG():
            new_24h = await db.fetchval(
                "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '1 day'"
            ) or 0
        else:
            new_24h = await db.fetchval(
                "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-1 day')"
            ) or 0
        banned     = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_banned = 1") or 0
        ai_done    = await db.fetchval(
            "SELECT COUNT(*) FROM generations WHERE mode = 'ai' AND status = 'done'"
        ) or 0
        pending    = await db.fetchval(
            "SELECT COUNT(*) FROM payments WHERE status = 'pending'") or 0
        total_paid = await db.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'"
        ) or 0
    return {
        "new_24h": new_24h, "banned": banned,
        "ai_done": ai_done, "pending_payments": pending,
        "total_paid": float(total_paid),
    }


async def _get_total_paid() -> float:
    async with _DB() as db:
        val = await db.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'"
        )
    return float(val or 0)


async def _set_ban(user_id: int, banned: bool) -> None:
    async with _DB() as db:
        await db.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (1 if banned else 0, user_id),
        )
        await db.commit()


async def _get_all_user_ids() -> list[int]:
    async with _DB() as db:
        rows = await db.fetchall(
            "SELECT user_id FROM users WHERE is_banned = 0", ()
        )
    return [r["user_id"] for r in rows]


async def _do_broadcast(bot: Bot, text: str) -> tuple[int, int, int]:
    ids = await _get_all_user_ids()
    sent = failed = blocked = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("blocked", "deactivated", "chat not found", "user not found")):
                blocked += 1
            else:
                failed += 1
        await asyncio.sleep(0.05)
    logger.info(f"Broadcast: sent={sent} blocked={blocked} failed={failed}")
    return sent, failed, blocked


# ── Gemini ────────────────────────────────────────────────

async def _check_gemini_quick() -> str:
    return "✅ Ключ задан" if GEMINI_API_KEY else "❌ Ключ не задан"


async def _check_gemini_full() -> str:
    if not GEMINI_API_KEY:
        return "❌ <b>GEMINI_API_KEY не задан</b>"
    MODELS  = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    PAYLOAD = {
        "contents": [{"role": "user", "parts": [{"text": "Reply: OK"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    lines  = ["🤖 <b>Статус Gemini API</b>\n"]
    any_ok = False
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
        for model in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            try:
                async with s.post(url, json=PAYLOAD) as r:
                    if r.status == 200:
                        lines.append(f"✅ <code>{model}</code> — работает")
                        any_ok = True
                    elif r.status == 429:
                        lines.append(f"⏳ <code>{model}</code> — квота (429)")
                        any_ok = True
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
    lines.append(
        "\n✅ <b>Как минимум одна модель работает</b>" if any_ok
        else "\n❌ <b>Ни одна модель не отвечает</b>"
    )
    return "\n".join(lines)


# ── Утилиты ───────────────────────────────────────────────

def _fmt_dt(val) -> str:
    s = str(val) if val else "—"
    return s[:16] if len(s) > 10 else s


def _back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main"))
    return b.as_markup()


def _cancel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"))
    return b.as_markup()


def _confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Отправить всем", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отмена",          callback_data="broadcast_cancel"),
    )
    return b.as_markup()
