"""
Система оплаты: Telegram Stars, CryptoBot, DonatePay (polling).

ИСПРАВЛЕНО: все функции работы с БД переведены с aiosqlite (только SQLite)
на универсальный _DB из bot.database.models (работает с PostgreSQL и SQLite).
Старый код напрямую открывал aiosqlite.connect(DB_PATH), что на Render
(где используется PostgreSQL через DATABASE_URL) приводило к ошибке
"no such table: payments" — физически создавался отдельный пустой
SQLite-файл вместо использования реальной Postgres БД.
"""
from __future__ import annotations
import asyncio
import logging
import time

import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice,
    PreCheckoutQuery, SuccessfulPayment,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import CRYPTOBOT_TOKEN, DONATEPAY_API_KEY, TARIFFS, RUBLES_PER_GEN
from bot.database import add_generations, get_user
from bot.database.models import _DB
from bot.keyboards import back_keyboard, main_menu_keyboard
from bot.services.message_manager import edit_clean

logger = logging.getLogger(__name__)
router = Router()

NAMES = {"start": "Старт", "basic": "Базовый", "pro": "Про", "ai_pack": "ИИ-пакет"}


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _tariff_info(tariff_key: str) -> dict | None:
    return TARIFFS.get(tariff_key)


async def _save_payment(user_id: int, method: str, tariff_key: str,
                         amount: float, stars: int, gens: int,
                         status: str, payload: str = "") -> None:
    async with _DB() as db:
        await db.execute(
            "INSERT INTO payments "
            "(user_id, method, tariff, amount, stars, gens_added, status, payload) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, method, tariff_key, amount, stars, gens, status, payload)
        )
        await db.commit()


async def _complete_payment(bot: Bot, user_id: int, gens: int,
                              ai: bool, method: str, tariff_key: str) -> None:
    await add_generations(user_id, gens, ai=ai)
    user_data = await get_user(user_id)
    bal  = user_data["generations"] if user_data else gens
    abal = user_data["ai_generations"] if user_data else 0
    gen_word = "ИИ-генераций" if ai else "генераций"
    await bot.send_message(
        user_id,
        f"✅ <b>Оплата прошла успешно!</b>\n\n"
        f"💳 Способ: {method}\n"
        f"🎁 Начислено: <b>{gens} {gen_word}</b>\n\n"
        f"🎨 Обычных: <b>{bal}</b>  |  🤖 ИИ: <b>{abal}</b>\n\n"
        "Нажми «🎨 Создать ресурспак» чтобы начать!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ── ⭐ TELEGRAM STARS ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars_invoice(call: CallbackQuery, bot: Bot):
    await call.answer()
    tariff_key = call.data.replace("pay_stars_", "")
    t = _tariff_info(tariff_key)
    if not t:
        return
    ai = tariff_key == "ai_pack"
    gen_word = "ИИ-генераций" if ai else "генераций"
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"🎮 {NAMES.get(tariff_key, tariff_key)}",
        description=f"{t['gens']} {gen_word} для Resourcepack Maker",
        payload=f"stars_{tariff_key}_{call.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{t['gens']} {gen_word}", amount=t["stars"])],
        provider_token="",
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def stars_payment_success(message: Message, bot: Bot):
    sp: SuccessfulPayment = message.successful_payment
    payload = sp.invoice_payload
    user_id = message.from_user.id

    if not payload.startswith("stars_"):
        return

    rest = payload[len("stars_"):]

    # ── Кастомный пакет: stars_custom_<amount>_<user_id> ──
    if rest.startswith("custom_"):
        inner = rest[len("custom_"):]
        sep = inner.rfind("_")
        if sep < 0:
            return
        try:
            gens = int(inner[:sep])
        except ValueError:
            return
        stars_paid = sp.total_amount
        await _save_payment(user_id, "stars", "custom",
                            round(gens * RUBLES_PER_GEN, 2),
                            stars_paid, gens, "paid",
                            sp.telegram_payment_charge_id)
        await _complete_payment(bot, user_id, gens, False, "⭐ Telegram Stars", "custom")
        return

    # ── Обычный тариф: stars_<tariff_key>_<user_id> ───────
    last_sep = rest.rfind("_")
    if last_sep < 0:
        return
    tariff_key = rest[:last_sep]
    t = _tariff_info(tariff_key)
    if not t:
        logger.error(f"Unknown tariff in Stars payload: '{tariff_key}' (raw: {payload})")
        return
    ai = tariff_key == "ai_pack"
    await _save_payment(user_id, "stars", tariff_key, t["rub"],
                        t["stars"], t["gens"], "paid",
                        sp.telegram_payment_charge_id)
    await _complete_payment(bot, user_id, t["gens"], ai, "⭐ Telegram Stars", tariff_key)


# ── ₿ CRYPTOBOT ──────────────────────────────────────────────────────────────

CRYPTOBOT_API = "https://pay.crypt.bot/api"


async def _cryptobot_request(method: str, params: dict) -> dict | None:
    if not CRYPTOBOT_TOKEN:
        return None
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{CRYPTOBOT_API}/{method}", json=params,
                              headers=headers,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                return data if data.get("ok") else None
    except Exception as e:
        logger.error(f"CryptoBot error: {e}")
        return None


@router.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto_invoice(call: CallbackQuery, bot: Bot):
    await call.answer()
    tariff_key = call.data.replace("pay_crypto_", "")
    t = _tariff_info(tariff_key)
    if not t:
        return

    if not CRYPTOBOT_TOKEN:
        await edit_clean(call.message,
            "⚠️ <b>CryptoBot не настроен</b>\n\nИспользуй другой способ оплаты.",
            back_keyboard("upgrade_plan"))
        return

    ai = tariff_key == "ai_pack"
    gen_word = "ИИ-генераций" if ai else "генераций"
    amount_usd = round(t["rub"] / 90, 2)
    payload_str = f"crypto_{tariff_key}_{call.from_user.id}_{int(time.time())}"

    result = await _cryptobot_request("createInvoice", {
        "asset": "USDT",
        "amount": str(amount_usd),
        "description": f"{NAMES.get(tariff_key)} — {t['gens']} {gen_word}",
        "payload": payload_str,
        "allow_anonymous": False,
        "expires_in": 3600,
    })

    if not result:
        await edit_clean(call.message,
            "❌ Не удалось создать инвойс CryptoBot. Попробуй позже.",
            back_keyboard("upgrade_plan"))
        return

    invoice = result["result"]
    pay_url = invoice["pay_url"]
    invoice_id = str(invoice["invoice_id"])

    await _save_payment(call.from_user.id, "cryptobot", tariff_key,
                        t["rub"], 0, t["gens"], "pending", invoice_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="₿ Оплатить через CryptoBot", url=pay_url))
    builder.row(InlineKeyboardButton(
        text="✅ Я оплатил — проверить",
        callback_data=f"ccheck_{invoice_id}_{tariff_key}_{call.from_user.id}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_plan"))

    await edit_clean(call.message,
        f"₿ <b>Оплата через CryptoBot</b>\n\n"
        f"💰 Сумма: <b>{amount_usd} USDT</b> (~{t['rub']} ₽)\n"
        f"📦 Тариф: <b>{NAMES.get(tariff_key)}</b> — {t['gens']} {gen_word}\n\n"
        "1. Нажми кнопку для оплаты\n"
        "2. После оплаты нажми «✅ Я оплатил»",
        builder.as_markup())


# ── Кастомный пакет через CryptoBot ──────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_crypto_custom_"))
async def pay_crypto_custom(call: CallbackQuery, bot: Bot):
    await call.answer()
    rest = call.data[len("pay_crypto_custom_"):]
    try:
        amount = int(rest)
    except ValueError:
        return

    if not CRYPTOBOT_TOKEN:
        await edit_clean(call.message,
            "⚠️ <b>CryptoBot не настроен</b>",
            back_keyboard("upgrade_plan"))
        return

    amount_usd = round(amount * RUBLES_PER_GEN / 90, 2)
    payload_str = f"crypto_custom_{amount}_{call.from_user.id}_{int(time.time())}"

    result = await _cryptobot_request("createInvoice", {
        "asset": "USDT",
        "amount": str(amount_usd),
        "description": f"Кастомный пакет {amount} генераций",
        "payload": payload_str,
        "allow_anonymous": False,
        "expires_in": 3600,
    })

    if not result:
        await edit_clean(call.message,
            "❌ Не удалось создать инвойс CryptoBot.",
            back_keyboard("upgrade_plan"))
        return

    invoice = result["result"]
    pay_url = invoice["pay_url"]
    invoice_id = str(invoice["invoice_id"])
    rub = round(amount * RUBLES_PER_GEN, 2)

    await _save_payment(call.from_user.id, "cryptobot", "custom",
                        rub, 0, amount, "pending", invoice_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="₿ Оплатить через CryptoBot", url=pay_url))
    builder.row(InlineKeyboardButton(
        text="✅ Я оплатил — проверить",
        callback_data=f"ccheck_{invoice_id}_{call.from_user.id}_custom_{amount}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_plan"))

    await edit_clean(call.message,
        f"₿ <b>Оплата через CryptoBot</b>\n\n"
        f"💰 Сумма: <b>{amount_usd} USDT</b> (~{rub} ₽)\n"
        f"📦 Кастомный пакет: <b>{amount} генераций</b>\n\n"
        "1. Нажми кнопку для оплаты\n"
        "2. После оплаты нажми «✅ Я оплатил»",
        builder.as_markup())


# ── Кастомный пакет через DonatePay ──────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_donate_custom_"))
async def pay_donate_custom(call: CallbackQuery, bot: Bot):
    await call.answer()
    rest = call.data[len("pay_donate_custom_"):]
    try:
        amount = int(rest)
    except ValueError:
        return

    if not DONATEPAY_API_KEY:
        await edit_clean(call.message,
            "⚠️ <b>DonatePay не настроен</b>",
            back_keyboard("upgrade_plan"))
        return

    rub = round(amount * RUBLES_PER_GEN, 2)
    ts = int(time.time())
    payload_str = f"dp_custom_{amount}_{call.from_user.id}_{ts}"
    await _save_payment(call.from_user.id, "donatepay", "custom",
                        rub, 0, amount, "pending", payload_str)

    donate_url = f"https://donatepay.ru/don/{await _get_donatepay_user_id()}"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Открыть страницу оплаты", url=donate_url))
    builder.row(InlineKeyboardButton(
        text="✅ Я оплатил — проверить",
        callback_data=f"dpcheck_{call.from_user.id}_{ts}_custom_{amount}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_plan"))

    await edit_clean(call.message,
        f"💳 <b>Оплата через DonatePay</b>\n\n"
        f"💰 Сумма: <b>{rub} ₽</b>\n"
        f"📦 Кастомный пакет: <b>{amount} генераций</b>\n\n"
        f"1. Нажми кнопку ниже\n"
        f"2. В поле <b>«Сообщение»</b> напиши: <code>{payload_str}</code>\n"
        f"3. Оплати {rub} ₽\n"
        f"4. Нажми «✅ Я оплатил»",
        builder.as_markup())


@router.callback_query(F.data.startswith("ccheck_"))
async def crypto_check_payment(call: CallbackQuery, bot: Bot):
    await call.answer("Проверяю...", show_alert=False)
    parts = call.data.split("_", 4)
    if len(parts) < 5:
        return
    invoice_id = parts[1]
    tariff_key = parts[2]
    user_id    = int(parts[3])

    result = await _cryptobot_request("getInvoices", {"invoice_ids": invoice_id})
    if not result or not result["result"]["items"]:
        await call.answer("Не удалось проверить платёж", show_alert=True)
        return

    status = result["result"]["items"][0].get("status")

    if status == "paid":
        t  = _tariff_info(tariff_key)
        ai = tariff_key == "ai_pack"
        async with _DB() as db:
            await db.execute(
                "UPDATE payments SET status='paid' WHERE payload=? AND user_id=?",
                (invoice_id, user_id)
            )
            await db.commit()
        await _complete_payment(bot, user_id, t["gens"], ai, "₿ CryptoBot", tariff_key)
        await edit_clean(call.message, "✅ Оплата подтверждена!", main_menu_keyboard())
    elif status == "active":
        await call.answer("⏳ Платёж ещё не поступил. Подожди немного.", show_alert=True)
    else:
        await call.answer(f"Статус: {status}", show_alert=True)


# ── 💳 DONATEPAY (polling) ───────────────────────────────────────────────────

DONATEPAY_API = "https://donatepay.ru/api/v1"


async def _donatepay_get(endpoint: str) -> dict | None:
    if not DONATEPAY_API_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{DONATEPAY_API}{endpoint}",
                params={"access_token": DONATEPAY_API_KEY},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
                return data if data.get("status") == "success" else None
    except Exception as e:
        logger.error(f"DonatePay error: {e}")
        return None


@router.callback_query(F.data.startswith("pay_donate_"))
async def pay_donatepay(call: CallbackQuery, bot: Bot):
    await call.answer()
    tariff_key = call.data.replace("pay_donate_", "")
    t = _tariff_info(tariff_key)
    if not t:
        return

    if not DONATEPAY_API_KEY:
        await edit_clean(call.message,
            "⚠️ <b>DonatePay не настроен</b>\n\nИспользуй другой способ оплаты.",
            back_keyboard("upgrade_plan"))
        return

    ai = tariff_key == "ai_pack"
    gen_word = "ИИ-генераций" if ai else "генераций"
    user_id = call.from_user.id

    ts = int(time.time())
    payload_str = f"dp_{tariff_key}_{user_id}_{ts}"
    await _save_payment(user_id, "donatepay", tariff_key,
                        t["rub"], 0, t["gens"], "pending", payload_str)

    donate_url = f"https://donatepay.ru/don/{await _get_donatepay_user_id()}"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Открыть страницу оплаты", url=donate_url))
    builder.row(InlineKeyboardButton(
        text="✅ Я оплатил — проверить",
        callback_data=f"dpcheck_{tariff_key}_{user_id}_{ts}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_plan"))

    await edit_clean(call.message,
        f"💳 <b>Оплата через DonatePay</b>\n\n"
        f"💰 Сумма: <b>{t['rub']} ₽</b>\n"
        f"📦 Тариф: <b>{NAMES.get(tariff_key)}</b> — {t['gens']} {gen_word}\n\n"
        f"1. Нажми кнопку ниже\n"
        f"2. В поле <b>«Сообщение»</b> напиши: <code>{payload_str}</code>\n"
        f"3. Оплати {t['rub']} ₽\n"
        f"4. Нажми «✅ Я оплатил»\n\n"
        f"⚠️ <i>Без сообщения бот не сможет подтвердить платёж!</i>",
        builder.as_markup())


@router.callback_query(F.data.startswith("dpcheck_"))
async def donatepay_check(call: CallbackQuery, bot: Bot):
    await call.answer("Проверяю...", show_alert=False)
    rest = call.data[len("dpcheck_"):]
    first_sep  = rest.find("_")
    second_sep = rest.find("_", first_sep+1)
    if first_sep < 0 or second_sep < 0:
        return
    user_id    = int(rest[:first_sep])
    ts         = int(rest[first_sep+1:second_sep])
    tariff_key = rest[second_sep+1:]

    custom_amount = None
    if tariff_key.startswith("custom_"):
        try:
            custom_amount = int(tariff_key.split("_", 1)[1])
        except ValueError:
            pass

    payload_str = f"dp_{tariff_key}_{user_id}_{ts}"

    result = await _donatepay_get("/transactions")
    if not result:
        await call.answer("Не удалось проверить. Попробуй позже.", show_alert=True)
        return

    transactions = result.get("data", [])
    found = None
    for tx in transactions:
        comment = tx.get("comment", "") or tx.get("message", "") or ""
        if payload_str in comment:
            tx_amount = float(tx.get("sum", 0))
            if tariff_key.startswith("custom_") and custom_amount:
                expected = round(custom_amount * RUBLES_PER_GEN, 2)
                if tx_amount >= expected * 0.99:
                    found = tx
                    break
            else:
                t = _tariff_info(tariff_key)
                if t and tx_amount >= t["rub"] * 0.99:
                    found = tx
                    break

    if found:
        async with _DB() as db:
            row = await db.fetchone(
                "SELECT status FROM payments WHERE payload = ?", (payload_str,)
            )
            if row and row.get("status") == "paid":
                await call.answer("Уже начислено!", show_alert=True)
                return
            await db.execute(
                "UPDATE payments SET status='paid' WHERE payload=?", (payload_str,)
            )
            await db.commit()

        if tariff_key.startswith("custom") and custom_amount:
            await _complete_payment(bot, user_id, custom_amount, False, "💳 DonatePay", "custom")
        else:
            t  = _tariff_info(tariff_key)
            ai = tariff_key == "ai_pack"
            if t:
                await _complete_payment(bot, user_id, t["gens"], ai, "💳 DonatePay", tariff_key)
        from bot.services.message_manager import edit_clean as ec
        await ec(call.message, "✅ Оплата подтверждена!", main_menu_keyboard())
    else:
        await call.answer(
            "❌ Платёж не найден.\n\nУбедись что указал правильный код в сообщении к донату.",
            show_alert=True
        )


# Кэш ID пользователя DonatePay
_donatepay_user_id_cache: str | None = None

async def _get_donatepay_user_id() -> str:
    global _donatepay_user_id_cache
    if _donatepay_user_id_cache:
        return _donatepay_user_id_cache
    result = await _donatepay_get("/user")
    if result:
        uid = result.get("data", {}).get("id", "")
        _donatepay_user_id_cache = str(uid)
        return _donatepay_user_id_cache
    return ""
