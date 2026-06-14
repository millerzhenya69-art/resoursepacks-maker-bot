"""
Обработчики раздела «Улучшить план».
Кастомное количество генераций — полная реализация.
"""
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.services.message_manager import edit_clean, send_clean, delete_user_message
from bot.keyboards import tariff_keyboard, tariff_payment_keyboard, back_keyboard
from bot.config import TARIFFS, STARS_PER_GEN, RUBLES_PER_GEN

router = Router()


class CustomGenState(StatesGroup):
    waiting_amount = State()


# ── Главный экран тарифов ──────────────────────────────────

@router.callback_query(F.data == "upgrade_plan")
async def upgrade_plan(call: CallbackQuery, state: FSMContext):
    try:
        await call.answer()
    except Exception:
        pass
    await state.clear()
    text = (
        "💎 <b>Улучшить план</b>\n\n"
        "Выбери тариф:\n\n"
        f"🚀 <b>Старт</b> — {TARIFFS['start']['gens']} генераций\n"
        f"    {TARIFFS['start']['stars']}⭐ или {TARIFFS['start']['rub']} ₽\n\n"
        f"⚡ <b>Базовый</b> — {TARIFFS['basic']['gens']} генераций\n"
        f"    {TARIFFS['basic']['stars']}⭐ или {TARIFFS['basic']['rub']} ₽\n\n"
        f"💎 <b>Про</b> — {TARIFFS['pro']['gens']} генераций\n"
        f"    {TARIFFS['pro']['stars']}⭐ или {TARIFFS['pro']['rub']} ₽\n\n"
        f"🤖 <b>ИИ-пакет</b> — {TARIFFS['ai_pack']['gens']} ИИ-генераций\n"
        f"    {TARIFFS['ai_pack']['stars']}⭐ или {TARIFFS['ai_pack']['rub']} ₽\n\n"
        f"🔢 <b>Кастомное</b> — любое кол-во\n"
        f"    {STARS_PER_GEN}⭐ или {RUBLES_PER_GEN} ₽ за генерацию"
    )
    await edit_clean(call.message, text, tariff_keyboard())


# ── Выбор тарифа ──────────────────────────────────────────

@router.callback_query(F.data.startswith("buy_"))
async def buy_tariff(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()
    except Exception:
        pass
    tariff_key = call.data.replace("buy_", "")

    # ── Кастомное количество ───────────────────────────────
    if tariff_key == "custom":
        await state.set_state(CustomGenState.waiting_amount)
        await state.update_data(chat_id=call.message.chat.id)
        await edit_clean(
            call.message,
            "🔢 <b>Кастомное количество генераций</b>\n\n"
            f"Цена: <b>{STARS_PER_GEN}⭐</b> или <b>{RUBLES_PER_GEN} ₽</b> за одну генерацию.\n\n"
            "Введи желаемое количество генераций <b>цифрой</b> (от 1 до 1000):",
            back_keyboard("upgrade_plan"),
        )
        return

    if tariff_key not in TARIFFS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    t = TARIFFS[tariff_key]
    names = {"start": "Старт", "basic": "Базовый", "pro": "Про", "ai_pack": "ИИ-пакет"}
    ai_note = " (ИИ-генерации)" if tariff_key == "ai_pack" else ""

    text = (
        f"💳 <b>Оплата тарифа «{names.get(tariff_key, tariff_key)}»</b>\n\n"
        f"📦 Количество: <b>{t['gens']} генераций{ai_note}</b>\n"
        f"💰 Цена: <b>{t['stars']}⭐</b> или <b>{t['rub']} ₽</b>\n\n"
        "Выбери способ оплаты:"
    )
    await edit_clean(call.message, text, tariff_payment_keyboard(tariff_key))


# ── Ввод кастомного количества ────────────────────────────

@router.message(CustomGenState.waiting_amount, F.text)
async def receive_custom_amount(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)

    text = message.text.strip()

    # Валидация
    if not text.isdigit():
        await send_clean(
            bot, message.chat.id,
            "⚠️ Введи <b>целое число</b>, например: <code>15</code>",
            back_keyboard("upgrade_plan"),
        )
        return

    amount = int(text)

    if amount < 1:
        await send_clean(
            bot, message.chat.id,
            "⚠️ Минимум <b>1 генерация</b>.",
            back_keyboard("upgrade_plan"),
        )
        return

    if amount > 1000:
        await send_clean(
            bot, message.chat.id,
            "⚠️ Максимум <b>1000 генераций</b> за один раз.",
            back_keyboard("upgrade_plan"),
        )
        return

    # Считаем цену — округляем вверх до целых звёзд (минимум 1)
    import math
    stars = max(1, math.ceil(amount * STARS_PER_GEN))
    rub   = round(amount * RUBLES_PER_GEN, 2)

    await state.update_data(custom_amount=amount, custom_stars=stars, custom_rub=rub)
    await state.clear()  # сбрасываем state — оплата через callback

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from bot.config import CRYPTOBOT_TOKEN, DONATEPAY_API_KEY
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"⭐ Оплатить {stars} Stars",
            callback_data=f"pay_stars_custom_{amount}_{stars}",
        )
    )
    if CRYPTOBOT_TOKEN:
        builder.row(
            InlineKeyboardButton(
                text="₿ Оплатить через CryptoBot",
                callback_data=f"pay_crypto_custom_{amount}",
            )
        )
    if DONATEPAY_API_KEY:
        builder.row(
            InlineKeyboardButton(
                text="💳 Оплатить через DonatePay",
                callback_data=f"pay_donate_custom_{amount}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_plan")
    )

    await send_clean(
        bot, message.chat.id,
        f"🔢 <b>Кастомный пакет</b>\n\n"
        f"📦 Генераций: <b>{amount}</b>\n"
        f"💰 Цена: <b>{stars}⭐</b> (~{rub} ₽)\n\n"
        "Выбери способ оплаты:",
        builder.as_markup(),
    )


# ── Оплата кастомного пакета через Stars ──────────────────
# Формат callback: pay_stars_custom_<amount>_<stars>

@router.callback_query(F.data.startswith("pay_stars_custom_"))
async def pay_stars_custom(call: CallbackQuery, bot: Bot):
    try:
        await call.answer()
    except Exception:
        pass

    # pay_stars_custom_<amount>_<stars>
    parts = call.data.split("_")
    # parts: ['pay','stars','custom', amount, stars]
    if len(parts) < 5:
        return

    try:
        amount = int(parts[3])
        stars  = int(parts[4])
    except ValueError:
        return

    from aiogram.types import LabeledPrice
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title="🎨 Кастомный пакет генераций",
        description=f"{amount} генераций для Resourcepack Maker",
        payload=f"stars_custom_{amount}_{call.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} генераций", amount=stars)],
        provider_token="",
    )


# ── Заглушка pay_ для остальных методов (реализованы в payment.py) ──

@router.callback_query(F.data.startswith("pay_"))
async def pay_method_fallback(call: CallbackQuery):
    # Этот handler срабатывает только если payment.py не перехватил
    # (payment.py регистрируется раньше в __init__.py)
    try:
        await call.answer()
    except Exception:
        pass
