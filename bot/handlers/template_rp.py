"""
Полный 11-шаговый FSM диалог шаблонного режима.
Шаги: оружие→броня→инструменты→еда/зелья→небо→GUI→звуки→цвет→меню→партикли→пожелание
"""
from __future__ import annotations
import asyncio
import json
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile

from bot.database import get_user, deduct_generation
from bot.database.models import DB_PATH
from bot.handlers.states import TemplateRP
from bot.keyboards_rp import (
    weapons_keyboard, armor_keyboard, tools_keyboard, consumables_keyboard,
    sky_keyboard, gui_keyboard, sounds_keyboard, color_keyboard,
    mainmenu_keyboard, particles_keyboard, confirm_keyboard, skip_keyboard,
)
from bot.services.message_manager import send_clean, edit_clean, delete_user_message
from bot.services.rp_builder import RPBuilder
from bot.services.rp_catalog import (
    WEAPONS, SKIES, GUIS, SOUNDS, PARTICLES, MAINMENUS,
    ARMOR, TOOLS, CONSUMABLES, COLOR_PRESETS,
)

logger = logging.getLogger(__name__)
router = Router()

THEME_HINTS = {
    "aggressive": "🔥 Агрессивный", "purple": "💜 Фиолетовый",
    "blue": "💙 Синий",             "gold": "✨ Золотой",
    "clean": "⬜ Чистый",           "green": "💚 Зелёный",
    "pvp": "⚔️ PvP",               "black": "🌑 Тёмный",
}

# Шаги в порядке прохождения
STEPS = [
    "weapons", "armor", "tools", "consumables",
    "sky", "gui", "sounds", "color", "mainmenu", "particles", "custom_wish"
]
STEP_TOTAL = len(STEPS)


def _step_num(step: str) -> int:
    return STEPS.index(step) + 1 if step in STEPS else 0


def _progress_header(step: str, data: dict) -> str:
    n = _step_num(step)
    done = []
    icons = {
        "weapons": "⚔️", "armor": "🛡️", "tools": "⛏️",
        "consumables": "🍎", "sky": "🌌", "gui": "📦",
        "sounds": "🔊", "color": "🎨", "mainmenu": "🏠",
        "particles": "✨",
    }
    for s in STEPS[:n-1]:
        label = data.get(f"{s}_label", "")
        if label:
            done.append(f"{icons.get(s,'•')} {label}")
    summary = "\n".join(done) if done else ""
    return f"<b>Шаг {n}/{STEP_TOTAL}</b>\n{summary}\n\n" if summary else f"<b>Шаг {n}/{STEP_TOTAL}</b>\n\n"


# ── Вход в диалог ─────────────────────────────────────────

async def start_template_dialog(call: CallbackQuery, state: FSMContext, bot: Bot, version: str):
    await state.set_state(TemplateRP.weapons)
    await state.update_data(version=version)
    await edit_clean(
        call.message,
        f"⚔️ <b>Шаг 1/{STEP_TOTAL} — Оружие</b>\n🎮 Версия: <b>{version}</b>\n\nВыбери стиль оружия:",
        weapons_keyboard(),
    )


# ── Шаг 1: Оружие ─────────────────────────────────────────

@router.callback_query(TemplateRP.weapons, F.data.startswith("wp:"))
async def step_weapons(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in WEAPONS if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(weapons=key, weapons_label=label)
    await state.set_state(TemplateRP.armor)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("armor", data) + "🛡️ Выбери стиль брони:",
        armor_keyboard())


# ── Шаг 2: Броня ──────────────────────────────────────────

@router.callback_query(TemplateRP.armor, F.data.startswith("arm:"))
async def step_armor(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in ARMOR if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(armor=key, armor_label=label)
    await state.set_state(TemplateRP.tools)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("tools", data) + "⛏️ Выбери стиль инструментов:",
        tools_keyboard())


# ── Шаг 3: Инструменты ────────────────────────────────────

@router.callback_query(TemplateRP.tools, F.data.startswith("tl:"))
async def step_tools(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in TOOLS if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(tools=key, tools_label=label)
    await state.set_state(TemplateRP.consumables)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("consumables", data) + "🍎 Выбери стиль еды и зелий:",
        consumables_keyboard())


# ── Шаг 4: Еда и зелья ────────────────────────────────────

@router.callback_query(TemplateRP.consumables, F.data.startswith("con:"))
async def step_consumables(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in CONSUMABLES if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(consumables=key, consumables_label=label)
    await state.set_state(TemplateRP.sky)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("sky", data) + "🌌 Выбери стиль неба:",
        sky_keyboard())


# ── Шаг 5: Небо ───────────────────────────────────────────

@router.callback_query(TemplateRP.sky, F.data.startswith("sky:"))
async def step_sky(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in SKIES if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(sky=key, sky_label=label)
    await state.set_state(TemplateRP.gui)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("gui", data) + "📦 Выбери стиль инвентаря:",
        gui_keyboard())


# ── Шаг 6: GUI ────────────────────────────────────────────

@router.callback_query(TemplateRP.gui, F.data.startswith("gui:"))
async def step_gui(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in GUIS if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(gui=key, gui_label=label)
    await state.set_state(TemplateRP.sounds)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("sounds", data) + "🔊 Выбери звуковой пак:",
        sounds_keyboard())


# ── Шаг 7: Звуки ──────────────────────────────────────────

@router.callback_query(TemplateRP.sounds, F.data.startswith("snd:"))
async def step_sounds(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in SOUNDS if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(sounds=key, sounds_label=label)
    await state.set_state(TemplateRP.color)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("color", data) +
        "🎨 Выбери цветовой тинт для оружия:\n<i>Или «🎨 Свой цвет» и введи HEX</i>",
        color_keyboard())


# ── Шаг 8: Цвет ───────────────────────────────────────────

@router.callback_query(TemplateRP.color, F.data.startswith("clr:"))
async def step_color_preset(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in COLOR_PRESETS if i["key"] == key), None)

    if key == "color_custom":
        await state.update_data(awaiting_hex=True)
        await edit_clean(call.message,
            "🎨 <b>Введи HEX цвет</b>\n\nНапример:\n"
            "<code>FF4444</code> — красный\n<code>FFD700</code> — золотой",
            skip_keyboard())
        return

    label   = item["label"] if item else key
    hex_val = item["hex"] if item else "FFFFFF"
    await state.update_data(color_hex=hex_val, color_label=label, awaiting_hex=False)
    await state.set_state(TemplateRP.mainmenu)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("mainmenu", data) + "🏠 Выбери стиль главного меню:",
        mainmenu_keyboard())


@router.message(TemplateRP.color)
async def step_color_text(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    data = await state.get_data()
    if not data.get("awaiting_hex"):
        return
    hex_val = message.text.strip().upper().lstrip("#")
    if len(hex_val) != 6 or not all(c in "0123456789ABCDEF" for c in hex_val):
        await send_clean(bot, message.chat.id,
            "❌ Неверный формат! Пример: <code>FF4444</code>", skip_keyboard())
        return
    await state.update_data(color_hex=hex_val, color_label=f"🎨 #{hex_val}", awaiting_hex=False)
    await state.set_state(TemplateRP.mainmenu)
    data = await state.get_data()
    await send_clean(bot, message.chat.id,
        _progress_header("mainmenu", data) + "🏠 Выбери стиль главного меню:",
        mainmenu_keyboard())


# ── Шаг 9: Главное меню ───────────────────────────────────

@router.callback_query(TemplateRP.mainmenu, F.data.startswith("mm:"))
async def step_mainmenu(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in MAINMENUS if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(mainmenu=key, mainmenu_label=label)
    await state.set_state(TemplateRP.particles)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("particles", data) + "✨ Выбери стиль партиклей:",
        particles_keyboard())


# ── Шаг 10: Партикли ──────────────────────────────────────

@router.callback_query(TemplateRP.particles, F.data.startswith("ptc:"))
async def step_particles(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    key = call.data.split(":", 1)[1]
    item = next((i for i in PARTICLES if i["key"] == key), None)
    label = item["label"] if item else key
    await state.update_data(particles=key, particles_label=label)
    await state.set_state(TemplateRP.custom_wish)
    data = await state.get_data()
    await edit_clean(call.message,
        _progress_header("custom_wish", data) +
        "💬 <b>Шаг 11/11 — Пожелание</b>\n\n"
        "Напиши любое пожелание (тема, стиль, детали)\n"
        "или нажми <b>«⏭ Пропустить»</b>:",
        skip_keyboard())


# ── Шаг 11: Пожелание ─────────────────────────────────────

@router.message(TemplateRP.custom_wish)
async def step_wish_text(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    await state.update_data(custom_wish=message.text.strip()[:500])
    await _show_confirm(bot, message.chat.id, state)


@router.callback_query(TemplateRP.custom_wish, F.data == "step_skip")
async def step_wish_skip(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    await state.update_data(custom_wish="")
    await _show_confirm(bot, call.message.chat.id, state)


# ── Подтверждение ─────────────────────────────────────────

async def _show_confirm(bot: Bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    wish_line = f"\n💬 {data['custom_wish'][:60]}" if data.get("custom_wish") else ""
    text = (
        f"📋 <b>Параметры ресурспака</b>\n\n"
        f"🎮 Версия: <b>{data.get('version')}</b>\n"
        f"⚔️ Оружие: {data.get('weapons_label','—')}\n"
        f"🛡️ Броня: {data.get('armor_label','—')}\n"
        f"⛏️ Инструменты: {data.get('tools_label','—')}\n"
        f"🍎 Еда/зелья: {data.get('consumables_label','—')}\n"
        f"🌌 Небо: {data.get('sky_label','—')}\n"
        f"📦 GUI: {data.get('gui_label','—')}\n"
        f"🔊 Звуки: {data.get('sounds_label','—')}\n"
        f"🎨 Цвет: {data.get('color_label','—')}\n"
        f"🏠 Меню: {data.get('mainmenu_label','—')}\n"
        f"✨ Партикли: {data.get('particles_label','—')}"
        f"{wish_line}\n\n"
        "Всё верно? Нажми <b>«✅ Собрать»</b>!"
    )
    await send_clean(bot, chat_id, text, confirm_keyboard())


# ── Сборка ────────────────────────────────────────────────

@router.callback_query(F.data == "rp_confirm")
async def rp_build(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    user_id = call.from_user.id

    user_data = await get_user(user_id)
    if not user_data or user_data["generations"] < 1:
        from bot.keyboards import tariff_keyboard
        await edit_clean(call.message,
            "😔 <b>Генерации закончились</b>\n\nПополни в разделе «💎 Улучшить план».",
            tariff_keyboard())
        await state.clear()
        return

    await state.set_state(TemplateRP.building)
    data = await state.get_data()

    wish = data.get("custom_wish", "")
    wish_line = f"\n💬 Тема: <i>{wish[:50]}</i>" if wish else ""

    await edit_clean(call.message,
        "⚙️ <b>Собираю ресурспак...</b>\n\n"
        f"🎮 Версия: <b>{data.get('version')}</b>{wish_line}\n\n"
        "⏳ Это займёт <b>1-2 минуты</b>:\n"
        "• 📦 Распаковка базового рп\n"
        "• 🎨 Наложение ассетов\n"
        "• 🌐 Поиск текстур\n"
        "• ✨ Тинт и упаковка\n\n"
        "Не закрывай чат, файл придёт автоматически! 📦")

    builder = RPBuilder(user_id=user_id, version=data.get("version","1.21.4"), params=data)

    build_steps = {
        "📦 Распаковка базового рп...":    "⚙️ <b>Сборка...</b> 1/4 📦 Распаковка",
        "🎨 Наложение шаблонов...":         "⚙️ <b>Сборка...</b> 2/4 🎨 Ассеты",
        "🌐 Поиск текстур...":              "⚙️ <b>Сборка...</b> 3/4 🌐 Поиск",
        "✨ Применение цвета и упаковка...": "⚙️ <b>Сборка...</b> 4/4 ✨ Упаковка",
    }

    async def on_progress(step: str):
        try:
            await call.message.edit_text(build_steps.get(step, step), parse_mode="HTML")
        except Exception:
            pass

    builder.set_progress_callback(on_progress)
    zip_path = await builder.build()

    if not zip_path:
        await send_clean(bot, call.message.chat.id,
            "❌ <b>Ошибка при сборке</b>\n\nГенерация не списана. "
            "Попробуй ещё раз или: @testpythonunkony_bot")
        await state.clear()
        return

    stats = builder.stats
    detected_theme = stats.get("theme", "pvp")
    theme_label = THEME_HINTS.get(detected_theme, "⚔️ PvP")
    web_note = f"\n🌐 Найдено в сети: <b>{stats['web_found']}</b> текстур" if stats["web_found"] else ""
    rp_filename = f"PvP_{detected_theme}_{data.get('version')}_by_unkony.zip"

    sent = False
    sent_file_id = None
    for attempt in range(3):
        try:
            doc = FSInputFile(zip_path, filename=rp_filename)
            ud = await get_user(user_id)
            gens_left = ud["generations"] if ud else 0

            sent_msg = await bot.send_document(
                chat_id=call.message.chat.id,
                document=doc,
                caption=(
                    f"✅ <b>Ресурспак готов!</b>\n\n"
                    f"🎨 Тема: <b>{theme_label}</b>\n"
                    f"🎮 Версия: <b>{data.get('version')}</b>\n"
                    f"⚔️ Оружие: {data.get('weapons_label','—')}\n"
                    f"🛡️ Броня: {data.get('armor_label','—')}\n"
                    f"🌌 Небо: {data.get('sky_label','—')}\n"
                    f"📦 GUI: {data.get('gui_label','—')}{web_note}\n\n"
                    f"🎨 Осталось генераций: <b>{gens_left - 1}</b>\n\n"
                    "📂 <code>.minecraft/resourcepacks/</code>"
                ),
                parse_mode="HTML",
                request_timeout=300,
            )
            sent_file_id = sent_msg.document.file_id if sent_msg.document else None
            await deduct_generation(user_id)
            await _log_generation(user_id, "template", data)
            sent = True
            break
        except Exception as e:
            logger.warning(f"Send attempt {attempt+1}/3: {e}")
            if attempt < 2:
                await asyncio.sleep(5)

    if not sent:
        await send_clean(bot, call.message.chat.id,
            "❌ Не удалось отправить файл.\n"
            "Генерация не списана. Обратись: @testpythonunkony_bot")

    builder.cleanup()
    builder.cleanup_zip()

    if sent and sent_file_id:
        # Спрашиваем об публикации в форум
        import time as _time
        rp_id = f"{user_id}_{int(_time.time())}"
        await state.update_data(
            publish_file_id=sent_file_id,
            publish_rp_id=rp_id,
            publish_rp_name=rp_filename,
            publish_caption=(
                f"🎨 <b>{rp_filename}</b>\n"
                f"Тема: {theme_label} | Версия: {data.get('version')}\n"
                f"⚔️ {data.get('weapons_label','—')} | 🛡️ {data.get('armor_label','—')}\n"
                f"🌌 {data.get('sky_label','—')} | 📦 {data.get('gui_label','—')}\n\n"
                f"Создано через @resourcepackmaker_bot"
            ),
        )
        from bot.keyboards import publish_rp_keyboard
        await send_clean(
            bot, call.message.chat.id,
            "📢 <b>Опубликовать данный РП</b> в <a href=\"https://t.me/forum_of_resoursepack_maker\">t.me/forum_of_resoursepack_maker</a>?",
            publish_rp_keyboard(rp_id),
        )
        # Не очищаем state — ждём ответа на публикацию
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


# ── Отмена / Редактирование ───────────────────────────────

@router.callback_query(F.data == "rp_cancel")
async def rp_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Отменено")
    await state.clear()
    from bot.keyboards import main_menu_keyboard
    await edit_clean(call.message, "❌ Создание отменено.", main_menu_keyboard())


@router.callback_query(F.data == "rp_edit")
async def rp_edit(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    data = await state.get_data()
    version = data.get("version", "1.21.4")
    await state.clear()
    await state.set_state(TemplateRP.weapons)
    await state.update_data(version=version)
    await edit_clean(call.message,
        f"⚔️ <b>Шаг 1/{STEP_TOTAL} — Оружие</b>\n🎮 Версия: <b>{version}</b>\n\nВыбери стиль оружия:",
        weapons_keyboard())


@router.callback_query(F.data == "step_skip")
async def step_skip(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    current = await state.get_state()

    next_map = {
        TemplateRP.armor.state:       (TemplateRP.tools,        "tools",       "⛏️ Выбери инструменты:",    tools_keyboard()),
        TemplateRP.tools.state:       (TemplateRP.consumables,  "consumables", "🍎 Выбери еду и зелья:",    consumables_keyboard()),
        TemplateRP.consumables.state: (TemplateRP.sky,          "sky",         "🌌 Выбери небо:",           sky_keyboard()),
        TemplateRP.sky.state:         (TemplateRP.gui,          "gui",         "📦 Выбери инвентарь:",      gui_keyboard()),
        TemplateRP.gui.state:         (TemplateRP.sounds,       "sounds",      "🔊 Выбери звуки:",          sounds_keyboard()),
        TemplateRP.sounds.state:      (TemplateRP.color,        "color",       "🎨 Выбери цвет тинта:",     color_keyboard()),
        TemplateRP.mainmenu.state:    (TemplateRP.particles,    "particles",   "✨ Выбери партикли:",        particles_keyboard()),
        TemplateRP.particles.state:   (TemplateRP.custom_wish,  "wish",        "💬 Напиши пожелание:",      skip_keyboard()),
        TemplateRP.custom_wish.state: (None, None, None, None),
    }

    if current == TemplateRP.custom_wish.state:
        await state.update_data(custom_wish="")
        await _show_confirm(bot, call.message.chat.id, state)
        return

    mapping = next_map.get(current)
    if mapping:
        next_state, param, text, kb = mapping
        if param:
            await state.update_data(**{param: None, f"{param}_label": "⏭ Пропущено"})
        if next_state:
            await state.set_state(next_state)
        if text and kb:
            data = await state.get_data()
            await edit_clean(call.message, _progress_header(param or "custom_wish", data) + text, kb)
    else:
        await _show_confirm(bot, call.message.chat.id, state)


# ── Сохранение в БД ──────────────────────────────────────

async def _log_generation(user_id: int, mode: str, params: dict):
    import aiosqlite
    safe = {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool, type(None)))}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO generations (user_id, mode, version, params, status) VALUES (?,?,?,?,?)",
            (user_id, mode, params.get("version","?"), json.dumps(safe), "done")
        )
        await db.commit()


# ── Публикация РП в форум-канал ───────────────────────────

async def _send_to_main_menu(bot: Bot, chat_id: int, user_id: int):
    """Общий финал: показываем главное меню."""
    ud = await get_user(user_id)
    gens    = ud["generations"]    if ud else 0
    ai_gens = ud["ai_generations"] if ud else 0
    from bot.keyboards import main_menu_keyboard
    await send_clean(
        bot, chat_id,
        f"🎮 <b>Resourcepack Maker</b>\n<i>by unkony</i>\n\n"
        f"🎨 Генераций: <b>{gens}</b>  |  🤖 ИИ: <b>{ai_gens}</b>",
        main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("rp_publish:"))
async def rp_publish(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    data = await state.get_data()

    file_id = data.get("publish_file_id")
    caption = data.get("publish_caption", "📦 Новый ресурспак")

    published = False
    if file_id:
        try:
            from bot.config import FORUM_CHANNEL
            await bot.send_document(
                chat_id=f"@{FORUM_CHANNEL}",
                document=file_id,
                caption=caption,
                parse_mode="HTML",
            )
            published = True
        except Exception as e:
            logger.warning(f"Publish to forum failed: {e}")

    if published:
        await send_clean(
            bot, call.message.chat.id,
            "✅ <b>РП опубликован!</b>\n\n"
            f"📢 Смотри в <a href=\"https://t.me/forum_of_resoursepack_maker\">t.me/forum_of_resoursepack_maker</a>",
        )
    else:
        await send_clean(
            bot, call.message.chat.id,
            "⚠️ Не удалось опубликовать. Убедись, что бот — админ канала.",
        )

    await state.clear()
    await _send_to_main_menu(bot, call.message.chat.id, call.from_user.id)


@router.callback_query(F.data == "rp_skip_publish")
async def rp_skip_publish(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()

    except Exception:
        pass
    await state.clear()
    await _send_to_main_menu(bot, call.message.chat.id, call.from_user.id)
