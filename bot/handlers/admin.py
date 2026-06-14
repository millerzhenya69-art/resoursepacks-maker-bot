"""
Команды администратора (только для ADMIN_ID).
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_ID
from bot.database import get_stats
from bot.services.message_manager import delete_user_message

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()
    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        f"👤 Пользователей: <b>{stats['users']}</b>\n"
        f"🎨 Генераций создано: <b>{stats['generations']}</b>\n"
        f"💳 Успешных платежей: <b>{stats['payments']}</b>\n\n"
        "Команды:\n"
        "/addgens <code>user_id</code> <code>кол-во</code> — добавить генерации\n"
        "/ban <code>user_id</code> — заблокировать пользователя\n"
        "/broadcast — рассылка (в разработке)"
    )
    await bot.send_message(message.chat.id, text, parse_mode="HTML")


@router.message(Command("addgens"))
async def cmd_addgens(message: Message, bot: Bot):
    await delete_user_message(message)
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await bot.send_message(message.chat.id, "Использование: /addgens <user_id> <кол-во>")
        return

    user_id, amount = int(parts[1]), int(parts[2])
    from bot.database import add_generations
    await add_generations(user_id, amount)
    await bot.send_message(
        message.chat.id,
        f"✅ Пользователю <code>{user_id}</code> добавлено <b>{amount}</b> генераций.",
        parse_mode="HTML"
    )
