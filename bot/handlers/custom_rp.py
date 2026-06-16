"""
Кастомный режим — пошаговый диалог.

Бот задаёт вопросы по каждому аспекту РП:
  1. Текстуры оружия (PNG/ZIP)
  2. Текстуры брони (PNG/ZIP)
  3. Текстуры GUI/инвентаря (PNG/ZIP)
  4. Небо/окружение (PNG/ZIP)
  5. Звуки ударов (OGG/ZIP)
  6. Партикли (PNG/ZIP)
  7. Иконка пака (PNG)
  → Подтверждение и сборка

На каждом шаге пользователь может пропустить («⏩ Пропустить»).
Загрузка строго классифицируется по текущему шагу — никакой путаницы.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import zipfile
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message, FSInputFile, Document,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import TEMP_DIR, PACKS_DIR
from bot.database import get_user, deduct_generation
from bot.database.models import DB_PATH
from bot.handlers.states import CustomRP
from bot.services.message_manager import send_clean, edit_clean, delete_user_message
from bot.services.rp_catalog import PACK_FORMATS
from bot.services.rp_builder import NEEDED_PREFIXES

logger = logging.getLogger(__name__)

router = Router()

MAX_UPLOAD_MB = 20  # Telegram Bot API ограничение: файлы > 20MB нельзя скачать через бота

# ── Шаги диалога ──────────────────────────────────────────

STEPS = [
    {
        "key":    "weapons",
        "title":  "⚔️ Оружие и инструменты",
        "prompt": (
            "⚔️ <b>Шаг 1/7 — Оружие и инструменты</b>\n\n"
            "Загрузи текстуры для оружия, кирок, топоров, лука и т.д.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/textures/item/</code>\n"
            "• <b>PNG-файлы</b> — напрямую (diamond_sword.png, bow.png и т.д.)\n\n"
            "Файлы попадут в <code>textures/item/</code>"
        ),
        "dest_path": "assets/minecraft/textures/item",
        "allowed":   [".zip", ".png", ".jpg", ".jpeg"],
    },
    {
        "key":    "armor",
        "title":  "🛡️ Броня",
        "prompt": (
            "🛡️ <b>Шаг 2/7 — Броня</b>\n\n"
            "Загрузи слои брони — это текстуры которые видны на персонаже.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/textures/models/armor/</code>\n"
            "• <b>PNG-файлы</b> — например <code>diamond_layer_1.png</code>, <code>diamond_layer_2.png</code>\n\n"
            "⚠️ Именно эти файлы отвечают за отображение брони на теле игрока"
        ),
        "dest_path": "assets/minecraft/textures/models/armor",
        "allowed":   [".zip", ".png"],
    },
    {
        "key":    "gui",
        "title":  "📦 GUI / Инвентарь",
        "prompt": (
            "📦 <b>Шаг 3/7 — GUI и инвентарь</b>\n\n"
            "Загрузи текстуры интерфейса — инвентарь, хотбар, иконки сердечек и голода.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/textures/gui/</code>\n"
            "• <b>PNG-файлы</b> — widgets.png, icons.png, container/inventory.png и т.д."
        ),
        "dest_path": "assets/minecraft/textures/gui",
        "allowed":   [".zip", ".png"],
    },
    {
        "key":    "sky",
        "title":  "🌌 Небо",
        "prompt": (
            "🌌 <b>Шаг 4/7 — Небо и окружение</b>\n\n"
            "Загрузи текстуры неба — солнце, луна, облака, дождь, снег.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/textures/environment/</code>\n"
            "• <b>PNG-файлы</b> — sun.png, moon_phases.png, clouds.png, rain.png, snow.png\n\n"
            "💡 Чёрное небо = просто удали/не загружай sun.png и moon_phases.png"
        ),
        "dest_path": "assets/minecraft/textures/environment",
        "allowed":   [".zip", ".png"],
    },
    {
        "key":    "sounds",
        "title":  "🔊 Звуки",
        "prompt": (
            "🔊 <b>Шаг 5/7 — Звуки</b>\n\n"
            "Загрузи звуки ударов, получения урона и других действий.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/sounds/</code>\n"
            "• <b>OGG-файлы</b> — напрямую (бот определит тип по имени файла)\n\n"
            "📁 <b>Структура звуков:</b>\n"
            "<code>sounds/entity/player/attack/</code> — звуки удара\n"
            "<code>sounds/entity/player/hurt/</code> — звуки урона"
        ),
        "dest_path": "assets/minecraft/sounds",
        "allowed":   [".zip", ".ogg"],
    },
    {
        "key":    "particles",
        "title":  "✨ Партикли",
        "prompt": (
            "✨ <b>Шаг 6/7 — Партикли</b>\n\n"
            "Загрузи текстуры частиц — критический удар, крови, магии и т.д.\n\n"
            "📎 <b>Что принимаю:</b>\n"
            "• <b>ZIP-архив</b> — с папкой <code>assets/minecraft/textures/particle/</code>\n"
            "• <b>PNG-файлы</b> — critical_hit.png, damage_indicator.png и т.д.\n\n"
            "💡 Маленькие партикли = залей 1x1 прозрачный PNG"
        ),
        "dest_path": "assets/minecraft/textures/particle",
        "allowed":   [".zip", ".png"],
    },
    {
        "key":    "icon",
        "title":  "🖼 Иконка пака",
        "prompt": (
            "🖼 <b>Шаг 7/7 — Иконка пака</b>\n\n"
            "Загрузи иконку которая будет отображаться в списке ресурспаков.\n\n"
            "📎 <b>Требования:</b>\n"
            "• PNG-файл, желательно <b>128×128</b> пикселей\n"
            "• Квадратное соотношение сторон\n\n"
            "Если не загрузишь — будет использована стандартная иконка бота"
        ),
        "dest_path": None,  # особый шаг — пишем прямо в корень
        "allowed":   [".png", ".jpg", ".jpeg"],
    },
]

STEP_KEYS = [s["key"] for s in STEPS]


# ── Вход ──────────────────────────────────────────────────

async def start_custom_dialog(call: CallbackQuery, state: FSMContext, bot: Bot, version: str):
    await state.set_state(CustomRP.upload)
    await state.update_data(
        version=version,
        step=0,
        uploads={},        # {step_key: [{"name":…, "path":…, "ext":…}]}
        work_dir=None,
    )
    await edit_clean(
        call.message,
        f"📁 <b>Кастомный режим</b> · версия <b>{version}</b>\n\n"
        "Бот проведёт тебя по 7 шагам — для каждого аспекта РП.\n"
        "На каждом шаге можно загрузить файлы или пропустить.",
        _next_step_keyboard(0, has_files=False),
    )
    await _show_step(bot, call.message.chat.id, 0)


# ── Показ шага ────────────────────────────────────────────

async def _show_step(bot: Bot, chat_id: int, step_idx: int):
    step = STEPS[step_idx]
    allowed_str = " / ".join(step["allowed"])
    await send_clean(
        bot, chat_id,
        step["prompt"] + f"\n\n<i>Принимаю: {allowed_str}</i>",
        _next_step_keyboard(step_idx, has_files=False),
    )


# ── Приём файлов ──────────────────────────────────────────

@router.message(CustomRP.upload, F.document)
async def receive_file(message: Message, state: FSMContext, bot: Bot):
    await delete_user_message(message)
    data = await state.get_data()
    step_idx: int = data.get("step", 0)
    step = STEPS[step_idx]
    uploads: dict = data.get("uploads", {})

    doc: Document = message.document
    fname = doc.file_name or "file"
    ext = os.path.splitext(fname)[1].lower()

    if ext not in step["allowed"]:
        await send_clean(
            bot, message.chat.id,
            f"⚠️ На шаге «{step['title']}» принимаю только: {', '.join(step['allowed'])}\n"
            f"Файл <code>{fname}</code> не подходит.",
            _next_step_keyboard(step_idx, has_files=bool(uploads.get(step["key"])))
        )
        return

    size_mb = (doc.file_size or 0) / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        await send_clean(bot, message.chat.id,
            f"⚠️ Файл слишком большой: <b>{size_mb:.1f} МБ</b>\n\n"
            f"Максимум — <b>{MAX_UPLOAD_MB} МБ</b> (ограничение Telegram API).\n\n"
            "💡 Сожми архив или раздели на несколько файлов.",
            _next_step_keyboard(step_idx, has_files=bool(uploads.get(step["key"]))))
        return

    user_id = message.from_user.id
    tmp_dir = os.path.join(TEMP_DIR, f"custom_{user_id}_{int(time.time())}")
    os.makedirs(tmp_dir, exist_ok=True)
    dest = os.path.join(tmp_dir, fname)

    try:
        # bot.download() работает для файлов любого размера (в отличие от get_file+download_file)
        await bot.download(doc, destination=dest)
    except Exception as e:
        logger.error(f"Download failed: {e}")
        await send_clean(bot, message.chat.id,
            "❌ Ошибка загрузки файла.\n"
            "Проверь что файл не повреждён и попробуй ещё раз.",
            _next_step_keyboard(step_idx, has_files=bool(uploads.get(step["key"]))))
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    step_uploads = uploads.get(step["key"], [])
    step_uploads.append({"name": fname, "path": dest, "ext": ext, "size_mb": round(size_mb, 2)})
    uploads[step["key"]] = step_uploads
    await state.update_data(uploads=uploads)

    file_list = "\n".join(f"  ✅ <code>{f['name']}</code> ({f['size_mb']} МБ)" for f in step_uploads)
    await send_clean(
        bot, message.chat.id,
        f"{step['title']} — загружено:\n{file_list}\n\n"
        "Можешь загрузить ещё или перейти дальше.",
        _next_step_keyboard(step_idx, has_files=True),
    )


# ── Кнопки навигации ──────────────────────────────────────

@router.callback_query(CustomRP.upload, F.data == "custom_next")
async def next_step(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()
    except Exception:
        pass
    data = await state.get_data()
    step_idx: int = data.get("step", 0)
    next_idx = step_idx + 1

    if next_idx >= len(STEPS):
        # Все шаги пройдены — показываем итог
        await _show_summary(call, state, bot)
        return

    await state.update_data(step=next_idx)
    await _show_step(bot, call.message.chat.id, next_idx)


@router.callback_query(CustomRP.upload, F.data == "custom_prev")
async def prev_step(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()
    except Exception:
        pass
    data = await state.get_data()
    step_idx: int = data.get("step", 0)
    if step_idx > 0:
        await state.update_data(step=step_idx - 1)
        await _show_step(bot, call.message.chat.id, step_idx - 1)


@router.callback_query(CustomRP.upload, F.data == "custom_build")
async def start_build(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer()
    except Exception:
        pass
    await _do_build(call, state, bot)


@router.callback_query(CustomRP.upload, F.data == "custom_cancel")
async def cancel_custom(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await call.answer("Отменено")
    except Exception:
        pass
    data = await state.get_data()
    _cleanup_uploads(data.get("uploads", {}))
    await state.clear()
    from bot.keyboards import main_menu_keyboard
    await edit_clean(call.message, "❌ Создание отменено.", main_menu_keyboard())


# ── Итоговая сводка перед сборкой ─────────────────────────

async def _show_summary(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    uploads: dict = data.get("uploads", {})
    version = data.get("version", "1.21.4")

    lines = []
    total_files = 0
    for step in STEPS:
        key = step["key"]
        files = uploads.get(key, [])
        if files:
            lines.append(f"  ✅ {step['title']}: {len(files)} файл(ов)")
            total_files += len(files)
        else:
            lines.append(f"  ⏩ {step['title']}: пропущено")

    summary = "\n".join(lines)

    if total_files == 0:
        await send_clean(
            bot, call.message.chat.id,
            "⚠️ Ты не загрузил ни одного файла!\n\nВернись назад и загрузи хотя бы что-нибудь.",
            _summary_keyboard()
        )
        return

    await send_clean(
        bot, call.message.chat.id,
        f"📋 <b>Итоговая сводка</b>\n\n"
        f"🎮 Версия: <b>{version}</b>\n\n"
        f"{summary}\n\n"
        f"📁 Всего загружено: <b>{total_files}</b> файл(ов)\n\n"
        "Собираем РП?",
        _summary_keyboard(),
    )


# ── Сборка ────────────────────────────────────────────────

async def _do_build(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    uploads: dict = data.get("uploads", {})
    version = data.get("version", "1.21.4")
    user_id = call.from_user.id

    user_data = await get_user(user_id)
    if not user_data or user_data["generations"] < 1:
        from bot.keyboards import tariff_keyboard
        await edit_clean(call.message,
            "😔 <b>Генерации закончились</b>\n\nПополни в «💎 Улучшить план».",
            tariff_keyboard())
        await state.clear()
        return

    total_files = sum(len(v) for v in uploads.values())
    await edit_clean(
        call.message,
        f"⚙️ <b>Собираю кастомный РП...</b>\n\n"
        f"🎮 Версия: <b>{version}</b>  |  Файлов: <b>{total_files}</b>\n\n"
        "⏳ Подожди немного...",
    )

    zip_path = await _build_custom_rp(user_id, version, uploads)

    if not zip_path:
        await send_clean(bot, call.message.chat.id,
            "❌ <b>Ошибка при сборке</b>\n\nГенерация не списана. "
            "Попробуй ещё раз или: @testpythonunkony_bot")
        _cleanup_uploads(uploads)
        await state.clear()
        return

    rp_filename = f"Custom_RP_{version}_by_unkony.zip"

    sent = False
    sent_file_id = None
    for attempt in range(3):
        try:
            doc_file = FSInputFile(zip_path, filename=rp_filename)
            ud = await get_user(user_id)
            gens_left = ud["generations"] if ud else 0

            sent_msg = await bot.send_document(
                chat_id=call.message.chat.id,
                document=doc_file,
                caption=(
                    f"✅ <b>Кастомный РП готов!</b>\n\n"
                    f"🎮 Версия: <b>{version}</b>\n"
                    f"📁 Встроено файлов: <b>{total_files}</b>\n\n"
                    f"🎨 Осталось генераций: <b>{gens_left - 1}</b>\n\n"
                    "📂 <code>.minecraft/resourcepacks/</code>"
                ),
                parse_mode="HTML",
                request_timeout=300,
            )
            sent_file_id = sent_msg.document.file_id if sent_msg.document else None
            await deduct_generation(user_id)
            await _log_custom(user_id, version, total_files)
            sent = True
            break
        except Exception as e:
            logger.warning(f"Send attempt {attempt+1}/3: {e}")
            if attempt < 2:
                await asyncio.sleep(5)

    try:
        os.remove(zip_path)
    except Exception:
        pass
    _cleanup_uploads(uploads)

    if not sent:
        await send_clean(bot, call.message.chat.id,
            "❌ Не удалось отправить файл. Генерация не списана.")
        await state.clear()
        return

    if sent_file_id:
        import time as _t
        rp_id = f"{user_id}_custom_{int(_t.time())}"
        await state.update_data(
            publish_file_id=sent_file_id,
            publish_rp_id=rp_id,
            publish_rp_name=rp_filename,
            publish_caption=(
                f"📁 <b>{rp_filename}</b>\n"
                f"Кастомный РП | Версия: {version}\n"
                f"Файлов: {total_files}\n\n"
                "Создано через @Resoursepack_maker_bot"
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
    from bot.keyboards import main_menu_keyboard
    await send_clean(bot, call.message.chat.id,
        f"🎮 <b>Resourcepack Maker</b>\n<i>by unkony</i>\n\n"
        f"🎨 Генераций: <b>{ud['generations'] if ud else 0}</b>  "
        f"|  🤖 ИИ: <b>{ud['ai_generations'] if ud else 0}</b>",
        main_menu_keyboard())


# ── Сборка ZIP ────────────────────────────────────────────

async def _build_custom_rp(user_id: int, version: str, uploads: dict) -> Optional[str]:
    work_dir = os.path.join(TEMP_DIR, f"custom_build_{user_id}_{int(time.time())}")
    out_zip  = os.path.join(TEMP_DIR, f"custom_{user_id}_{int(time.time())}.zip")

    try:
        os.makedirs(work_dir, exist_ok=True)

        # Базовый пак
        base_zip = os.path.join(PACKS_DIR, f"base_{version}.zip")
        if os.path.exists(base_zip):
            with zipfile.ZipFile(base_zip, "r") as zf:
                for member in zf.infolist():
                    name = member.filename
                    if name.endswith("/"):
                        continue
                    if not any(name.startswith(p) for p in NEEDED_PREFIXES):
                        if name not in ("pack.mcmeta", "pack.png"):
                            continue
                    dest_path = os.path.join(work_dir, name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with zf.open(member) as src, open(dest_path, "wb") as dst:
                        dst.write(src.read())

        # Встраиваем файлы пользователя по шагам
        for step in STEPS:
            step_files = uploads.get(step["key"], [])
            for f in step_files:
                _embed_file(f, step, work_dir)

        # Equipment JSON для брони (1.21.2+)
        _inject_equipment_json(work_dir)

        # pack.mcmeta
        fmt = PACK_FORMATS.get(version, {"pack_format": 46})
        pack_format = fmt["pack_format"]
        mcmeta = {
            "pack": {
                "pack_format": pack_format,
                "supported_formats": [34, 999],  # широкий диапазон — совместим со всеми 1.21.x
                "description": f"Custom RP {version} by unkony",
            }
        }
        with open(os.path.join(work_dir, "pack.mcmeta"), "w", encoding="utf-8") as mf:
            json.dump(mcmeta, mf, indent=2, ensure_ascii=False)

        # Упаковка
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, _, files in os.walk(work_dir):
                for file in files:
                    fp  = os.path.join(root, file)
                    arc = os.path.relpath(fp, work_dir)
                    zf.write(fp, arc, compress_type=zipfile.ZIP_DEFLATED)

        return out_zip

    except Exception as e:
        logger.error(f"Custom build error: {e}", exc_info=True)
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _embed_file(f: dict, step: dict, work_dir: str):
    ext  = f["ext"]
    path = f["path"]
    name = f["name"]
    dest_rel = step["dest_path"]

    if ext == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for member in zf.infolist():
                    mname = member.filename
                    if mname.endswith("/"):
                        continue
                    dest = os.path.join(work_dir, mname)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        dst.write(src.read())
        except Exception as e:
            logger.warning(f"ZIP embed error for {name}: {e}")

    elif ext in (".png", ".jpg", ".jpeg"):
        basename = os.path.splitext(name)[0] + ".png"

        # Особый шаг — иконка пака
        if step["key"] == "icon":
            try:
                from PIL import Image
                img = Image.open(path).convert("RGBA")
                img = img.resize((128, 128))
                img.save(os.path.join(work_dir, "pack.png"), "PNG")
            except Exception:
                shutil.copy2(path, os.path.join(work_dir, "pack.png"))
            return

        if dest_rel:
            dest_dir = os.path.join(work_dir, dest_rel)
            os.makedirs(dest_dir, exist_ok=True)
            dest_file = os.path.join(dest_dir, basename)
            if ext in (".jpg", ".jpeg"):
                try:
                    from PIL import Image
                    img = Image.open(path).convert("RGBA")
                    img.save(dest_file, "PNG")
                except Exception:
                    shutil.copy2(path, dest_file)
            else:
                shutil.copy2(path, dest_file)

    elif ext == ".ogg":
        # OGG → определяем куда класть по имени файла
        lname = name.lower()
        if any(k in lname for k in ("attack", "hit", "crit", "strong", "weak", "sweep", "knock")):
            sub = "entity/player/attack"
        elif any(k in lname for k in ("hurt", "damage", "pain")):
            sub = "entity/player/hurt"
        else:
            sub = "entity/player/attack"  # дефолт

        dest_dir = os.path.join(work_dir, "assets", "minecraft", "sounds", sub)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(dest_dir, name))


def _inject_equipment_json(work_dir: str):
    """Создаёт equipment/*.json для корректного отображения брони в 1.21.2+"""
    armor_dir = os.path.join(work_dir, "assets", "minecraft", "textures", "models", "armor")
    if not os.path.isdir(armor_dir):
        return

    equipment_dir = os.path.join(work_dir, "assets", "minecraft", "equipment")
    os.makedirs(equipment_dir, exist_ok=True)

    MATERIALS = {
        "diamond":   ("diamond_layer_1",  "diamond_layer_2"),
        "iron":      ("iron_layer_1",      "iron_layer_2"),
        "gold":      ("gold_layer_1",      "gold_layer_2"),
        "netherite": ("netherite_layer_1", "netherite_layer_2"),
        "chainmail": ("chainmail_layer_1", "chainmail_layer_2"),
        "leather":   ("leather_layer_1",   "leather_layer_2"),
    }

    for material, (l1, l2) in MATERIALS.items():
        if not os.path.exists(os.path.join(armor_dir, f"{l1}.png")):
            continue
        j = {"layers": [{"texture": f"minecraft:{l1}"}]}
        if os.path.exists(os.path.join(armor_dir, f"{l2}.png")):
            j["layers"].append({
                "texture": f"minecraft:{l2}",
                "dyeable": material == "leather",
            })
        with open(os.path.join(equipment_dir, f"{material}.json"), "w") as fh:
            json.dump(j, fh, indent=2)


def _cleanup_uploads(uploads: dict):
    for step_files in uploads.values():
        for f in step_files:
            try:
                os.remove(f["path"])
                os.rmdir(os.path.dirname(f["path"]))
            except Exception:
                pass


# ── Клавиатуры ────────────────────────────────────────────

def _next_step_keyboard(step_idx: int, has_files: bool):
    builder = InlineKeyboardBuilder()
    is_last = step_idx >= len(STEPS) - 1

    if is_last:
        builder.row(InlineKeyboardButton(
            text="📋 Показать итог", callback_data="custom_next"))
    else:
        label = "⏩ Пропустить" if not has_files else "➡️ Следующий шаг"
        builder.row(InlineKeyboardButton(text=label, callback_data="custom_next"))

    if step_idx > 0:
        builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="custom_prev"))

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="custom_cancel"))
    return builder.as_markup()


def _summary_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Собрать РП", callback_data="custom_build"))
    builder.row(InlineKeyboardButton(text="◀️ Назад к шагам", callback_data="custom_prev"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="custom_cancel"))
    return builder.as_markup()


# ── Логирование ───────────────────────────────────────────

async def _log_custom(user_id: int, version: str, file_count: int):
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO generations (user_id, mode, version, params, status) VALUES (?,?,?,?,?)",
            (user_id, "custom", version,
             json.dumps({"file_count": file_count}), "done")
        )
        await db.commit()
