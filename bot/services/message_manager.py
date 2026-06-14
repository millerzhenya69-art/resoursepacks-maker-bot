"""
MessageManager — хранит ID последнего сообщения бота для каждого пользователя
и удаляет его перед отправкой нового. Чат остаётся чистым.
"""
from __future__ import annotations
from typing import Optional

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

# user_id → message_id последнего сообщения бота
_last_msg: dict[int, int] = {}


async def send_clean(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    photo: Optional[str] = None,
) -> Message:
    """
    Удаляет предыдущее сообщение бота и отправляет новое.
    Сохраняет ID нового сообщения для последующего удаления.
    """
    await _delete_last(bot, chat_id)

    if photo:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    else:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

    _last_msg[chat_id] = msg.message_id
    return msg


async def edit_clean(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> Message:
    """
    Редактирует текущее сообщение бота (предпочтительнее отправки нового —
    меньше мигания в чате).
    """
    try:
        edited = await message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        _last_msg[message.chat.id] = edited.message_id
        return edited
    except TelegramBadRequest:
        # Если сообщение не изменилось или уже удалено — отправляем новое
        return await send_clean(
            message.bot, message.chat.id, text, reply_markup, parse_mode
        )


async def _delete_last(bot: Bot, chat_id: int) -> None:
    msg_id = _last_msg.pop(chat_id, None)
    if msg_id:
        try:
            await bot.delete_message(chat_id, msg_id)
        except TelegramBadRequest:
            pass  # уже удалено или слишком старое


async def delete_user_message(message: Message) -> None:
    """Удаляет сообщение самого пользователя (например, команду /start)."""
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
