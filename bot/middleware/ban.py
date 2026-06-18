"""
Middleware проверки бана.
Забаненные пользователи получают отказ на любое взаимодействие.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery

from bot.config import ADMIN_ID
from bot.database import get_user


class BanMiddleware(BaseMiddleware):
    """
    Перехватывает все апдейты. Если пользователь забанен —
    молча игнорирует (или отправляет уведомление).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Извлекаем user_id из апдейта
        user_id: int | None = None

        if isinstance(event, Update):
            if event.message and event.message.from_user:
                user_id = event.message.from_user.id
            elif event.callback_query and event.callback_query.from_user:
                user_id = event.callback_query.from_user.id

        # Администратора никогда не блокируем
        if user_id and user_id != ADMIN_ID:
            user = await get_user(user_id)
            if user and user.get("is_banned"):
                # Уведомляем пользователя и прекращаем обработку
                if isinstance(event, Update):
                    bot = data.get("bot")
                    if bot:
                        try:
                            if event.message:
                                await event.message.reply(
                                    "🚫 Ваш аккаунт заблокирован. "
                                    "Обратитесь в поддержку: @testpythonunkony_bot"
                                )
                            elif event.callback_query:
                                await event.callback_query.answer(
                                    "🚫 Ваш аккаунт заблокирован.",
                                    show_alert=True,
                                )
                        except Exception:
                            pass
                return  # Не передаём апдейт дальше

        return await handler(event, data)
