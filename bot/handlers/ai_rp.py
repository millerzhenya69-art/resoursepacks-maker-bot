"""
ИИ-режим создания ресурспака.

Диалог:
  1. Пользователь вводит свободный промпт
  2. Gemini подбирает комбинацию шаблонов
  3. Бот показывает preview выбора + кнопки:
       ✅ Собрать РП  |  ✏️ Уточнить  |  🔄 Перегенерировать  |  ❌ Отмена
  4. Пользователь может уточнить → история сохраняется → Gemini корректирует
  5. После подтверждения — тот же RPBuilder что в шаблонном режиме
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import TEMP_DIR
from bot.database import get_user, deduct_generation
from bot.database.models import DB_PATH
from bot.handlers.states import AIRP
from bot.services.gemini_service import ask_gemini, gemini_params_to_rp_params
from bot.services.message_manager import send_clean, edit_clean, delete_user_message
from bot.services.rp_builder import RPBuilder
from bot.services.rp_catalog import (
    WEAPONS, ARMOR, TOOLS, CONSUMABLES, SKIES, GUIS, SOUNDS, PARTICLES, MAINMENUS
)

logger = logging.getLogger(__name__)

router = Router()

# Для быстрого получения label по key
_LABEL_MAP: dict[str, str] = {}
for _lst in (WEAPONS, ARMOR, TOOLS, CONSUMABLES, SKIES, GUIS, SOUNDS, PARTICLES, MAINMENUS):
    for _item in _lst:
        _LABEL_MAP[_item["key"]] = _item["label"]


# ── Вход из create_rp ─────────────────────────────────────

async def start_ai_dialog(call: CallbackQuery, state: FSMContext, bot: Bot, version: str):
    await state.set_state(AIRP.prompt)
    await state.update_data(
        version=version,
        history=[],          # история диалога с Gemini
        iteration=0,         # счётчик уточнений
        last_ai_params=None, # последний ответ Gemini
    )
    await edit_clean(
        call.message,
        f"🤖 <b>ИИ-режим</b> · версия <b>{version}</b>\n\n"
        "Опиши какой ресурспак ты хочешь — любыми словами:\n\n"
        "<i>Примеры:\n"
        '• "Тёмный агрессивный PvP с фиолетовыми частицами"\n'
        '• "Ретро стиль, как в старом Minecraft, яркие цвета"\n'
        '• "Мрачный мифический пак, алмазная броня, резкие звуки удара"\n'
        '• "Максимум FPS, минимум визуала, чёрное небо"</i>',
        _cancel_keyboard(),
    )


# ── Приём промпта ─────────────────────────────────────────

@router.message(AIRP.prompt, F.text)
async def receive_prompt(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    data = await state.get_data()

    prompt = message.text.strip()
    if len(prompt) < 3:
        await send_clean(bot, message.chat.id,
            "✏️ Промпт слишком короткий. Опиши подробнее что хочешь:", _cancel_keyboard())
        return

    if len(prompt) > 1000:
        prompt = prompt[:1000]

    # Показываем "думаю..."
    thinking_msg = await send_clean(
        bot, message.chat.id,
        "🤖 <b>Gemini подбирает комбинацию...</b>\n\n"
        f"<i>Запрос: «{prompt[:80]}{'...' if len(prompt)>80 else ''}»</i>"
    )

    data = await state.get_data()
    history: list = data.get("history", [])
    iteration: int = data.get("iteration", 0)

    # Запрашиваем Gemini
    ai_params, error = await ask_gemini(prompt, history)

    if error or not ai_params:
        await _delete_thinking(bot, message.chat.id, thinking_msg)
        await send_clean(bot, message.chat.id,
            f"❌ <b>Ошибка ИИ:</b> {error or 'неизвестная ошибка'}\n\n"
            "Попробуй ещё раз или измени запрос.",
            _cancel_keyboard())
        return

    # Обновляем историю для следующей итерации
    history.append({"role": "user",  "text": prompt})
    history.append({"role": "model", "text": json.dumps(ai_params, ensure_ascii=False)})

    await state.update_data(
        history=history,
        iteration=iteration + 1,
        last_ai_params=ai_params,
        last_prompt=prompt,
    )

    await _delete_thinking(bot, message.chat.id, thinking_msg)
    await _show_ai_preview(bot, message.chat.id, state, ai_params, iteration + 1)


# ── Показ preview ─────────────────────────────────────────

async def _show_ai_preview(
    bot: Bot, chat_id: int, state: FSMContext,
    ai_params: dict, iteration: int,
):
    explanation = ai_params.get("explanation", "")
    suggestions = ai_params.get("suggestions", "")

    # Красивый список выбранных компонентов
    fields = [
        ("⚔️ Оружие",    ai_params.get("weapons")),
        ("🛡️ Броня",     ai_params.get("armor")),
        ("⛏️ Инструменты", ai_params.get("tools")),
        ("🍎 Еда/зелья", ai_params.get("consumables")),
        ("🌌 Небо",      ai_params.get("sky")),
        ("📦 GUI",       ai_params.get("gui")),
        ("🔊 Звуки",     ai_params.get("sounds")),
        ("✨ Партикли",  ai_params.get("particles")),
        ("🏠 Меню",      ai_params.get("mainmenu")),
    ]

    color_hex = ai_params.get("color_hex")
    if color_hex and color_hex.lower() not in ("null", "none", ""):
        fields.append(("🎨 Цвет тинта", f"#{color_hex}"))

    components = "\n".join(
        f"  {emoji} <b>{name}:</b> {_LABEL_MAP.get(key, key)}"
        for emoji_name, key in [(f[0], f[1]) for f in fields]
        for name, emoji in [(" ".join(emoji_name.split()[1:]), emoji_name.split()[0])]
        if key
    )

    # Переформатируем для читаемости
    lines = []
    for label, key in fields:
        if key:
            human = _LABEL_MAP.get(key, key)
            lines.append(f"  {label}: <b>{human}</b>")
    components = "\n".join(lines)

    text = (
        f"🤖 <b>ИИ подобрал комбинацию</b>"
        + (f" (итерация {iteration})" if iteration > 1 else "") + "\n\n"
        f"{components}\n\n"
    )
    if explanation:
        text += f"💬 <i>{explanation}</i>\n\n"
    if suggestions:
        text += f"💡 <b>Идеи:</b> <i>{suggestions}</i>\n\n"

    text += "Что делаем?"

    await send_clean(bot, chat_id, text, _preview_keyboard())


# ── Кнопки после preview ──────────────────────────────────

@router.callback_query(AIRP.prompt, F.data == "ai_build")
async def ai_build(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    data = await state.get_data()
    ai_params = data.get("last_ai_params")
    version = data.get("version", "1.21.4")

    if not ai_params:
        await call.answer("⚠️ Нет данных для сборки", show_alert=True)
        return

    user_id = call.from_user.id
    user_data = await get_user(user_id)
    if not user_data or user_data["ai_generations"] < 1:
        from bot.keyboards import tariff_keyboard
        await edit_clean(call.message,
            "😔 <b>ИИ-генерации закончились</b>\n\nПополни в «💎 Улучшить план».",
            tariff_keyboard())
        await state.clear()
        return

    await edit_clean(
        call.message,
        "⚙️ <b>Собираю ИИ-ресурспак...</b>\n\n"
        "⏳ Это займёт 10–30 секунд...",
    )

    # Конвертируем params Gemini → params для RPBuilder
    rp_params = gemini_params_to_rp_params(ai_params, version)

    # Лейблы для caption
    rp_params["weapons_label"]    = _LABEL_MAP.get(rp_params["weapons"], "—")
    rp_params["armor_label"]      = _LABEL_MAP.get(rp_params["armor"], "—")
    rp_params["sky_label"]        = _LABEL_MAP.get(rp_params["sky"], "—")
    rp_params["gui_label"]        = _LABEL_MAP.get(rp_params["gui"], "—")

    # Собираем с прогресс-колбэком
    last_progress_text = {"v": ""}
    async def progress_cb(text: str):
        if text == last_progress_text["v"]:
            return
        last_progress_text["v"] = text
        try:
            await edit_clean(
                call.message,
                f"⚙️ <b>Собираю ИИ-ресурспак...</b>\n\n{text}",
            )
        except Exception:
            pass

    builder = RPBuilder(user_id, version, rp_params)
    builder.set_progress_callback(progress_cb)
    zip_path = await builder.build()

    if not zip_path:
        await send_clean(bot, call.message.chat.id,
            "❌ <b>Ошибка при сборке</b>\n\nГенерация не списана. "
            "Попробуй ещё раз или: @testpythonunkony_bot")
        await state.clear()
        return

    theme = rp_params.get("detected_theme", "AI")
    rp_filename = f"AI_{theme}_{version}_by_unkony.zip"

    sent = False
    sent_file_id = None
    for attempt in range(3):
        try:
            doc = FSInputFile(zip_path, filename=rp_filename)
            ud = await get_user(user_id)
            ai_gens_left = (ud["ai_generations"] if ud else 0) - 1

            explanation_short = (ai_params.get("explanation", "") or "")[:200]

            sent_msg = await bot.send_document(
                chat_id=call.message.chat.id,
                document=doc,
                caption=(
                    f"🤖 <b>ИИ-ресурспак готов!</b>\n\n"
                    f"🎮 Версия: <b>{version}</b>\n"
                    f"⚔️ {rp_params['weapons_label']} · 🛡️ {rp_params['armor_label']}\n"
                    f"🌌 {rp_params['sky_label']} · 📦 {rp_params['gui_label']}\n\n"
                    + (f"💬 <i>{explanation_short}</i>\n\n" if explanation_short else "")
                    + f"🤖 Осталось ИИ-генераций: <b>{ai_gens_left}</b>\n\n"
                    "📂 <code>.minecraft/resourcepacks/</code>"
                ),
                parse_mode="HTML",
                request_timeout=120,
            )
            sent_file_id = sent_msg.document.file_id if sent_msg.document else None
            await deduct_generation(user_id, ai=True)
            await _log_ai_generation(user_id, version, rp_params, ai_params.get("explanation",""))
            sent = True
            break
        except Exception as e:
            logger.warning(f"Send attempt {attempt+1}/3: {e}")
            if attempt < 2:
                await asyncio.sleep(5)

    builder.cleanup()
    builder.cleanup_zip()

    if not sent:
        await send_clean(bot, call.message.chat.id,
            "❌ Не удалось отправить файл.\n"
            "ИИ-генерация не списана. Обратись: @testpythonunkony_bot")
        await state.clear()
        return

    if sent_file_id:
        import time as _time
        rp_id = f"{user_id}_ai_{int(_time.time())}"
        await state.update_data(
            publish_file_id=sent_file_id,
            publish_rp_id=rp_id,
            publish_rp_name=rp_filename,
            publish_caption=(
                f"🤖 <b>{rp_filename}</b>\n"
                f"ИИ-режим | Версия: {version}\n"
                f"⚔️ {rp_params['weapons_label']} · 🛡️ {rp_params['armor_label']}\n"
                + (f"💬 {(ai_params.get('explanation','') or '')[:150]}\n\n" if ai_params.get('explanation') else "\n")
                + "Создано через @resourcepackmaker_bot"
            ),
        )
        from bot.keyboards import publish_rp_keyboard
        await send_clean(
            bot, call.message.chat.id,
            "📢 <b>Опубликовать данный РП</b> в "
            "<a href=\"https://t.me/forum_of_resoursepack_maker\">t.me/forum_of_resoursepack_maker</a>?",
            publish_rp_keyboard(rp_id),
        )
        return

    await state.clear()
    ud = await get_user(user_id)
    gens = ud["generations"] if ud else 0
    ai_gens = ud["ai_generations"] if ud else 0
    from bot.keyboards import main_menu_keyboard
    await send_clean(bot, call.message.chat.id,
        f"🎮 <b>Resourcepack Maker</b>\n<i>by unkony</i>\n\n"
        f"🎨 Генераций: <b>{gens}</b>  |  🤖 ИИ: <b>{ai_gens}</b>",
        main_menu_keyboard())


@router.callback_query(AIRP.prompt, F.data == "ai_refine")
async def ai_refine(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    await edit_clean(
        call.message,
        "✏️ <b>Уточни что изменить:</b>\n\n"
        "<i>Примеры:\n"
        '• "Сделай звуки более резкими"\n'
        '• "Поменяй небо на чёрное"\n'
        '• "Хочу другие партикли, что-нибудь мифическое"\n'
        '• "Всё хорошо, но оружие сделай ярче"</i>',
        _cancel_keyboard(),
    )
    # Остаёмся в AIRP.prompt — следующий message придёт как уточнение с историей


@router.callback_query(AIRP.prompt, F.data == "ai_regenerate")
async def ai_regenerate(call: CallbackQuery, state: FSMContext, bot: Bot):
    """Перегенерировать с тем же промптом, но без истории → свежий взгляд."""
    await call.answer()
    data = await state.get_data()
    last_prompt = data.get("last_prompt", "")

    if not last_prompt:
        await call.answer("⚠️ Промпт не сохранён", show_alert=True)
        return

    # Сбрасываем историю но сохраняем промпт
    await state.update_data(history=[], iteration=0)

    await edit_clean(
        call.message,
        "🔄 <b>Перегенерирую с новым настроением...</b>\n\n"
        f"<i>Запрос: «{last_prompt[:80]}»</i>",
    )

    ai_params, error = await ask_gemini(last_prompt, [])
    if error or not ai_params:
        await send_clean(bot, call.message.chat.id,
            f"❌ <b>Ошибка:</b> {error}",
            _cancel_keyboard())
        return

    history = [
        {"role": "user",  "text": last_prompt},
        {"role": "model", "text": json.dumps(ai_params, ensure_ascii=False)},
    ]
    await state.update_data(history=history, iteration=1, last_ai_params=ai_params)
    await _show_ai_preview(bot, call.message.chat.id, state, ai_params, 1)


@router.callback_query(AIRP.prompt, F.data == "ai_cancel")
async def ai_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Отменено")
    await state.clear()
    from bot.keyboards import main_menu_keyboard
    ud = await get_user(call.from_user.id)
    gens = ud["generations"] if ud else 0
    ai_gens = ud["ai_generations"] if ud else 0
    await edit_clean(
        call.message,
        f"🎮 <b>Resourcepack Maker</b>\n<i>by unkony</i>\n\n"
        f"🎨 Генераций: <b>{gens}</b>  |  🤖 ИИ: <b>{ai_gens}</b>",
        main_menu_keyboard(),
    )


# ── Клавиатуры ────────────────────────────────────────────

def _preview_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Собрать РП",         callback_data="ai_build"),
        InlineKeyboardButton(text="✏️ Уточнить",           callback_data="ai_refine"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Перегенерировать",   callback_data="ai_regenerate"),
        InlineKeyboardButton(text="❌ Отмена",             callback_data="ai_cancel"),
    )
    return builder.as_markup()


def _cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="ai_cancel"))
    return builder.as_markup()


# ── Хелпер для удаления "думаю..." ────────────────────────

async def _delete_thinking(bot: Bot, chat_id: int, msg):
    if msg is None:
        return
    try:
        msg_id = msg if isinstance(msg, int) else getattr(msg, "message_id", None)
        if msg_id:
            await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


# ── Логирование ───────────────────────────────────────────

async def _log_ai_generation(
    user_id: int, version: str, rp_params: dict, explanation: str
):
    import aiosqlite
    safe = {k: v for k, v in rp_params.items()
            if isinstance(v, (str, int, float, bool, type(None)))}
    safe["ai_explanation"] = explanation[:200] if explanation else ""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO generations (user_id, mode, version, params, status) VALUES (?,?,?,?,?)",
            (user_id, "ai", version, json.dumps(safe, ensure_ascii=False), "done")
        )
        await db.commit()
