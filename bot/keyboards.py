"""
Все клавиатуры бота собраны в одном месте.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import REQUIRED_CHANNELS, TARIFFS, STARS_PER_GEN, RUBLES_PER_GEN


# ── Подписка ──────────────────────────────────────────────

def subscription_keyboard(not_subscribed: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки для каналов на которые нужно подписаться + кнопка проверки."""
    builder = InlineKeyboardBuilder()
    for ch in not_subscribed:
        builder.row(
            InlineKeyboardButton(
                text=f"📢 {ch['title']}",
                url=ch["url"]
            )
        )
    builder.row(
        InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="check_sub")
    )
    return builder.as_markup()


# ── Главное меню ──────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎨 Создать ресурспак", callback_data="create_rp")
    )
    builder.row(
        InlineKeyboardButton(text="💎 Улучшить план", callback_data="upgrade_plan"),
        InlineKeyboardButton(text="👤 Мой профиль",   callback_data="profile"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Реферальная ссылка", callback_data="referral"),
        InlineKeyboardButton(text="❓ Помощь",              callback_data="help"),
    )
    return builder.as_markup()


# ── Выбор режима создания ─────────────────────────────────

def create_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📦 Шаблонный",     callback_data="mode_template")
    )
    builder.row(
        InlineKeyboardButton(text="📁 Кастомный",     callback_data="mode_custom")
    )
    builder.row(
        InlineKeyboardButton(text="🤖 ИИ-генерация",  callback_data="mode_ai")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад",          callback_data="main_menu")
    )
    return builder.as_markup()


# ── Версии ────────────────────────────────────────────────

def version_keyboard(callback_prefix: str = "ver") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="1.21.4",  callback_data=f"{callback_prefix}_ver_1.21.4"),
        InlineKeyboardButton(text="1.21.8",  callback_data=f"{callback_prefix}_ver_1.21.8"),
        InlineKeyboardButton(text="1.21.11", callback_data=f"{callback_prefix}_ver_1.21.11"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="create_rp")
    )
    return builder.as_markup()


# ── Тарифы ────────────────────────────────────────────────

def tariff_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"🚀 Старт — {TARIFFS['start']['gens']} ген. / {TARIFFS['start']['stars']}⭐",
            callback_data="buy_start"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"⚡ Базовый — {TARIFFS['basic']['gens']} ген. / {TARIFFS['basic']['stars']}⭐",
            callback_data="buy_basic"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"💎 Про — {TARIFFS['pro']['gens']} ген. / {TARIFFS['pro']['stars']}⭐",
            callback_data="buy_pro"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🤖 ИИ-пакет — {TARIFFS['ai_pack']['gens']} ген. / {TARIFFS['ai_pack']['stars']}⭐",
            callback_data="buy_ai_pack"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔢 Кастомное количество", callback_data="buy_custom")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
    )
    return builder.as_markup()


def tariff_payment_keyboard(tariff_key: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты для конкретного тарифа."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Telegram Stars",  callback_data=f"pay_stars_{tariff_key}"),
    )
    builder.row(
        InlineKeyboardButton(text="₿ CryptoBot",        callback_data=f"pay_crypto_{tariff_key}"),
        InlineKeyboardButton(text="💳 DonatePay",        callback_data=f"pay_donate_{tariff_key}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад",            callback_data="upgrade_plan")
    )
    return builder.as_markup()


# ── Кнопка "Назад в меню" ─────────────────────────────────

def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    )
    return builder.as_markup()


def back_keyboard(callback: str = "main_menu", text: str = "◀️ Назад") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=text, callback_data=callback))
    return builder.as_markup()


# ── Публикация РП в канал ──────────────────────────────────

def publish_rp_keyboard(rp_id: str) -> InlineKeyboardMarkup:
    """Кнопки «Да / Нет» для публикации РП в форум-канал."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, опубликовать", callback_data=f"rp_publish:{rp_id}"),
        InlineKeyboardButton(text="❌ Нет",              callback_data="rp_skip_publish"),
    )
    return builder.as_markup()
