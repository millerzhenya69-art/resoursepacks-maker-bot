"""
Обработчики /start и проверки подписки.
"""
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery

from bot.database import get_or_create_user, get_user
from bot.services.subscription import check_subscriptions, mark_all_bots_started
from bot.services.message_manager import send_clean, edit_clean, delete_user_message
from bot.keyboards import subscription_keyboard, main_menu_keyboard
from bot.config import FREE_GENERATIONS

router = Router()


# ── /start ────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    await delete_user_message(message)

    # Реферальный код из /start?start=REF_CODE
    ref_code = command.args if command.args else None

    user = message.from_user
    await get_or_create_user(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name,
        ref_code=ref_code,
    )

    # Проверяем подписки
    not_subscribed = await check_subscriptions(bot, user.id)
    if not_subscribed:
        await send_clean(
            bot=bot,
            chat_id=message.chat.id,
            text=_sub_required_text(len(not_subscribed)),
            reply_markup=subscription_keyboard(not_subscribed),
        )
        return

    await _show_main_menu(bot, message.chat.id, user.id)


# ── Проверка подписки (кнопка) ────────────────────────────

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery, bot: Bot):
    await call.answer()
    # Помечаем боты как «запущенные» — Telegram API не позволяет проверить иначе
    await mark_all_bots_started(call.from_user.id)
    not_subscribed = await check_subscriptions(bot, call.from_user.id)

    if not_subscribed:
        await edit_clean(
            message=call.message,
            text=_sub_required_text(len(not_subscribed), retry=True),
            reply_markup=subscription_keyboard(not_subscribed),
        )
        return

    await _show_main_menu(bot, call.message.chat.id, call.from_user.id)


# ── Главное меню (callback) ───────────────────────────────

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(call: CallbackQuery, bot: Bot):
    await call.answer()
    await _show_main_menu(bot, call.message.chat.id, call.from_user.id)


# ── Профиль ───────────────────────────────────────────────

@router.callback_query(F.data == "profile")
async def profile_callback(call: CallbackQuery, bot: Bot):
    await call.answer()
    user_data = await get_user(call.from_user.id)
    if not user_data:
        return

    from bot.keyboards import back_to_menu_keyboard
    gens      = user_data["generations"]
    ai_gens   = user_data["ai_generations"]
    total     = user_data["total_generated"]
    ref_code  = user_data["referral_code"]
    ref_link  = f"https://t.me/{(await bot.get_me()).username}?start={ref_code}"

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"👤 Имя: {call.from_user.full_name}\n\n"
        f"🎨 Обычных генераций: <b>{gens}</b>\n"
        f"🤖 ИИ-генераций: <b>{ai_gens}</b>\n"
        f"📊 Всего создано: <b>{total}</b>\n\n"
        f"🔗 Реферальная ссылка:\n<code>{ref_link}</code>\n"
        f"<i>За каждого приглашённого — +2 генерации</i>"
    )
    await edit_clean(call.message, text, back_to_menu_keyboard())


# ── Реферальная ссылка ────────────────────────────────────

@router.callback_query(F.data == "referral")
async def referral_callback(call: CallbackQuery, bot: Bot):
    await call.answer()
    user_data = await get_user(call.from_user.id)
    if not user_data:
        return

    from bot.keyboards import back_to_menu_keyboard
    ref_code = user_data["referral_code"]
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={ref_code}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай <b>+2 генерации</b> за каждого!\n\n"
        f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        f"Просто отправь её другу — как только он запустит бота, "
        f"генерации зачислятся автоматически."
    )
    await edit_clean(call.message, text, back_to_menu_keyboard())


# ── Помощь ────────────────────────────────────────────────

@router.callback_query(F.data == "help")
async def help_callback(call: CallbackQuery, bot: Bot):
    await call.answer()
    from bot.keyboards import back_to_menu_keyboard
    text = (
        "❓ <b>Помощь</b>\n\n"
        "<b>Как создать ресурспак?</b>\n"
        "Нажми «🎨 Создать ресурспак» и выбери режим:\n"
        "• <b>Шаблонный</b> — выбираешь параметры кнопками\n"
        "• <b>Кастомный</b> — загружаешь свои ассеты\n"
        "• <b>ИИ</b> — описываешь словами, ИИ собирает\n\n"
        "<b>Сколько генераций?</b>\n"
        f"При старте — {FREE_GENERATIONS} бесплатных.\n"
        "Больше — в разделе «💎 Улучшить план».\n\n"
        "<b>Поддержка:</b> @testpythonunkony_bot"
    )
    await edit_clean(call.message, text, back_to_menu_keyboard())


# ── Внутренние хелперы ────────────────────────────────────

async def _show_main_menu(bot: Bot, chat_id: int, user_id: int):
    user_data = await get_user(user_id)
    gens    = user_data["generations"] if user_data else 0
    ai_gens = user_data["ai_generations"] if user_data else 0

    text = (
        "🎮 <b>Resourcepack Maker</b>\n"
        "<i>by unkony</i>\n\n"
        "Создавай PvP ресурспаки для Minecraft\n"
        "версий <b>1.21.4 · 1.21.8 · 1.21.11</b>\n\n"
        f"🎨 Генераций: <b>{gens}</b>  |  🤖 ИИ: <b>{ai_gens}</b>\n\n"
        "Выбери действие:"
    )
    await send_clean(bot, chat_id, text, main_menu_keyboard())


def _sub_required_text(count: int, retry: bool = False) -> str:
    prefix = "❌ <b>Ты ещё не подписался</b> на " if retry else "👋 <b>Привет!</b>\n\nДля использования бота подпишись на "
    channels_word = "все каналы" if count > 1 else "канал"
    return (
        f"{prefix}{channels_word} ниже.\n\n"
        "После подписки нажми кнопку <b>«✅ Я подписался»</b>."
    )
