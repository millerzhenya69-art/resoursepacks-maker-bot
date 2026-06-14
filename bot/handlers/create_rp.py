"""
Точка входа в создание ресурспака — выбор режима и версии.
После выбора передаёт управление соответствующему FSM-обработчику.
"""
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.database import get_user
from bot.services.message_manager import edit_clean
from bot.keyboards import create_mode_keyboard, version_keyboard, back_keyboard

router = Router()

MODE_NAMES = {
    "template": "📦 Шаблонный",
    "custom":   "📁 Кастомный",
    "ai":       "🤖 ИИ-генерация",
}
MODE_NOTES = {
    "template": "Выбирай параметры кнопками — бот соберёт рп из шаблонов.",
    "custom":   "Загружай свои текстуры и звуки — бот встроит их в рп.",
    "ai":       "Опиши желаемый рп словами — Gemini AI сделает остальное.\n<i>Тратит ИИ-генерацию.</i>",
}


@router.callback_query(F.data == "create_rp")
async def create_rp(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    await state.clear()  # сбрасываем любое предыдущее состояние

    user_data = await get_user(call.from_user.id)
    gens    = user_data["generations"] if user_data else 0
    ai_gens = user_data["ai_generations"] if user_data else 0

    if gens < 1 and ai_gens < 1:
        from bot.keyboards import tariff_keyboard
        await edit_clean(
            call.message,
            "😔 <b>Генерации закончились</b>\n\n"
            "У тебя не осталось генераций.\n"
            "Пополни баланс в разделе «💎 Улучшить план».",
            tariff_keyboard(),
        )
        return

    text = (
        "🎨 <b>Создать ресурспак</b>\n\n"
        f"Доступно: 🎨 <b>{gens}</b> обычных  |  🤖 <b>{ai_gens}</b> ИИ\n\n"
        "Выбери режим создания:\n\n"
        "📦 <b>Шаблонный</b> — выбираешь параметры кнопками\n"
        "📁 <b>Кастомный</b> — загружаешь свои ассеты\n"
        "🤖 <b>ИИ</b> — описываешь словами, ИИ собирает рп"
    )
    await edit_clean(call.message, text, create_mode_keyboard())


@router.callback_query(F.data.in_({"mode_template", "mode_custom", "mode_ai"}))
async def choose_mode(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    mode_key = call.data.replace("mode_", "")

    if mode_key == "ai":
        user_data = await get_user(call.from_user.id)
        if not user_data or user_data["ai_generations"] < 1:
            from bot.keyboards import tariff_keyboard
            await edit_clean(
                call.message,
                "🤖 <b>ИИ-генерация</b>\n\n"
                "Для ИИ-режима нужен <b>ИИ-пакет</b>.\n"
                "У тебя нет ИИ-генераций.\n\n"
                "Купи <b>ИИ-пакет (200⭐)</b> в разделе «Улучшить план».",
                back_keyboard("create_rp"),
            )
            return

    await state.update_data(mode=mode_key)
    name = MODE_NAMES[mode_key]
    note = MODE_NOTES[mode_key]
    await edit_clean(
        call.message,
        f"✅ Режим: <b>{name}</b>\n\n{note}\n\nВыбери версию Minecraft:",
        version_keyboard(f"mode_{mode_key}"),
    )


@router.callback_query(F.data.regexp(r"^mode_(template|custom|ai)_ver_\d+\.\d+"))
async def choose_version(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    # mode_template_ver_1.21.4  →  split на "_ver_"
    parts    = call.data.split("_ver_", 1)
    mode_key = parts[0].replace("mode_", "")
    version  = parts[1]

    await state.update_data(mode=mode_key, version=version)

    if mode_key == "template":
        from bot.handlers.template_rp import start_template_dialog
        await start_template_dialog(call, state, bot, version)

    elif mode_key == "custom":
        from bot.handlers.custom_rp import start_custom_dialog
        await start_custom_dialog(call, state, bot, version)

    elif mode_key == "ai":
        from bot.handlers.ai_rp import start_ai_dialog
        await start_ai_dialog(call, state, bot, version)
