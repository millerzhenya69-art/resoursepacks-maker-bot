"""
Сервис для работы с Gemini API.

Иерархия моделей:
  1. gemini-2.5-flash      (v1beta) — основная
  2. gemini-2.0-flash      (v1beta) — fallback при 429
  3. gemini-2.0-flash-lite (v1beta) — самый дешёвый запасной

Исправления:
  - maxOutputTokens увеличен до 4096 (был 2048 — JSON обрезался)
  - Добавлена проверка на обрезанный JSON (finishReason != STOP)
  - Более мягкий парсинг с попыткой восстановить обрезанный объект
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

import aiohttp

from bot.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _build_system_prompt() -> str:
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "rp_catalog",
        os.path.join(os.path.dirname(__file__), "rp_catalog.py")
    )
    cat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cat)

    catalog: dict[str, list] = {
        "weapons":     cat.WEAPONS,
        "armor":       cat.ARMOR,
        "tools":       cat.TOOLS,
        "consumables": cat.CONSUMABLES,
        "sky":         cat.SKIES,
        "gui":         cat.GUIS,
        "sounds":      cat.SOUNDS,
        "particles":   cat.PARTICLES,
        "mainmenu":    cat.MAINMENUS,
    }

    lines = []
    for section, items in catalog.items():
        lines.append(f"\n## {section.upper()}")
        for i in items:
            lines.append(f'  key="{i["key"]}"  label="{i["label"]}"  desc="{i["desc"]}"')

    return f"""Ты — ИИ-ассистент для создания Minecraft PvP ресурспаков.
Твоя задача: понять желание пользователя и собрать оптимальную комбинацию ассетов из каталога.

=== КАТАЛОГ ДОСТУПНЫХ ШАБЛОНОВ ===
{chr(10).join(lines)}

=== ПРАВИЛА ===
1. Отвечай ТОЛЬКО валидным JSON без Markdown-блоков и без пояснений вне JSON.
2. Структура ответа СТРОГО (все поля обязательны):
{{
  "weapons":     "<key>",
  "armor":       "<key>",
  "tools":       "<key>",
  "consumables": "<key>",
  "sky":         "<key>",
  "gui":         "<key>",
  "sounds":      "<key>",
  "particles":   "<key>",
  "mainmenu":    "<key>",
  "color_hex":   "<hex без # или null>",
  "explanation": "<1 краткое предложение почему, на русском>",
  "suggestions": "<1 короткая идея, на русском>"
}}
3. Используй ТОЛЬКО ключи из каталога выше.
4. explanation и suggestions — МАКСИМУМ 80 символов каждое. Краткость критична.
5. Понимай метафоры: "мрачный"→dark/pvp403, "огненный"→pvp394/pvp398, "ледяной"→crystal/pvp415.
6. При уточнении — сохраняй остальные параметры, меняй только указанное.
7. color_hex — тинт для оружия без символа #. null если не указано.
"""


try:
    SYSTEM_PROMPT = _build_system_prompt()
except Exception as e:
    logger.error(f"Failed to build system prompt: {e}")
    SYSTEM_PROMPT = "You are a Minecraft resource pack assistant. Respond with JSON only."


def _try_fix_truncated_json(raw: str) -> Optional[dict]:
    """
    Пытается восстановить обрезанный JSON-объект.
    Стратегия: берём все полностью завершённые строковые ключи.
    """
    result = {}
    # Ищем все завершённые пары "key": "value"
    pattern = re.compile(r'"(\w+)"\s*:\s*"([^"]*)"')
    for match in pattern.finditer(raw):
        key, val = match.group(1), match.group(2)
        result[key] = val
    # Ищем null-значения
    null_pattern = re.compile(r'"(\w+)"\s*:\s*null')
    for match in null_pattern.finditer(raw):
        result[match.group(1)] = None
    return result if result else None


async def ask_gemini(
    user_prompt: str,
    history: list[dict] | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Отправляет запрос Gemini. Все модели — через v1beta.
    При 429 — пауза 3 сек и следующая модель.
    """
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY не настроен в .env"

    contents = []
    if history:
        for msg in history:
            contents.append({
                "role": msg["role"],
                "parts": [{"text": msg["text"]}],
            })
    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.9,
            "maxOutputTokens": 4096,        # ← увеличено с 2048, чтобы JSON не обрезался
            "responseMimeType": "application/json",
        },
    }

    last_error = "Неизвестная ошибка"
    quota_count = 0

    for model in GEMINI_MODELS:
        url = f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as resp:

                    if resp.status == 429:
                        quota_count += 1
                        logger.warning(f"Gemini {model} quota exceeded (429)")
                        last_error = (
                            "⏳ Превышен лимит ИИ-запросов.\n\n"
                            "Бесплатный план: 10 запросов/минуту.\n"
                            "Подожди 1 минуту и попробуй снова."
                        )
                        await asyncio.sleep(3)
                        continue

                    if resp.status == 403:
                        await resp.text()
                        logger.error(f"Gemini {model} 403 — неверный ключ")
                        return None, "❌ Неверный GEMINI_API_KEY. Проверь ключ в .env"

                    if resp.status == 404:
                        await resp.text()
                        logger.warning(f"Gemini {model} not found (404)")
                        last_error = f"Модель {model} недоступна"
                        continue

                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Gemini {model} HTTP {resp.status}: {body[:300]}")
                        last_error = f"Ошибка Gemini API ({resp.status})"
                        continue

                    data = await resp.json()

                    # Проверяем причину завершения — MAX_TOKENS означает обрезанный ответ
                    try:
                        finish_reason = (
                            data["candidates"][0]
                            .get("finishReason", "STOP")
                        )
                        if finish_reason == "MAX_TOKENS":
                            logger.warning(
                                f"Gemini {model} hit MAX_TOKENS — JSON may be truncated"
                            )
                    except (KeyError, IndexError):
                        finish_reason = "STOP"

                    try:
                        raw = data["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError):
                        logger.error(f"Gemini {model} unexpected response: {str(data)[:200]}")
                        last_error = "Не удалось разобрать ответ ИИ"
                        continue

                    # Очищаем markdown-обёртки
                    clean = raw.strip()
                    clean = re.sub(r"```(?:json)?", "", clean)
                    clean = re.sub(r"```", "", clean)
                    clean = clean.strip()

                    # Извлекаем JSON объект между первым { и последним }
                    start = clean.find("{")
                    end   = clean.rfind("}") + 1
                    if start >= 0 and end > start:
                        clean = clean[start:end]

                    try:
                        params = json.loads(clean)
                    except json.JSONDecodeError as je:
                        logger.warning(
                            f"Gemini {model} JSON parse failed ({je}), "
                            f"trying truncation recovery..."
                        )
                        # Пытаемся восстановить обрезанный JSON
                        params = _try_fix_truncated_json(clean)
                        if not params:
                            logger.error(f"Recovery failed. Raw: {clean[:300]}")
                            last_error = "ИИ вернул невалидный JSON"
                            continue

                    # Проверяем наличие обязательных полей
                    required = {"weapons", "armor", "tools", "consumables",
                                "sky", "gui", "sounds", "particles", "mainmenu"}
                    missing = required - set(params.keys())
                    if missing:
                        logger.warning(f"Gemini {model} missing fields: {missing}")
                        # Подставляем дефолты для отсутствующих полей
                        defaults = {
                            "weapons":     "sword_pvp398",
                            "armor":       "armor_pvp398",
                            "tools":       "tools_pvp398",
                            "consumables": "consumables_pvp398",
                            "sky":         "sky_black",
                            "gui":         "gui_pvp403",
                            "sounds":      "sounds_pvp",
                            "particles":   "particles_none",
                            "mainmenu":    "menu_pvp403",
                        }
                        for field in missing:
                            params[field] = defaults.get(field, "")
                        logger.info(f"Applied defaults for missing fields: {missing}")

                    logger.info(f"Gemini OK via {model}")
                    return params, None

        except aiohttp.ClientError as e:
            logger.error(f"Gemini {model} network error: {e}")
            last_error = "Ошибка сети при обращении к Gemini"
        except Exception as e:
            logger.error(f"Gemini {model} error: {e}", exc_info=True)
            last_error = "Неожиданная ошибка ИИ"

    if quota_count == len(GEMINI_MODELS):
        return None, (
            "⏳ <b>Превышен лимит ИИ-запросов.</b>\n\n"
            "Бесплатный план Gemini: <b>10 запросов в минуту</b>.\n"
            "Подожди 1 минуту и попробуй снова."
        )

    return None, last_error


def gemini_params_to_rp_params(ai_params: dict, version: str) -> dict:
    color_hex = ai_params.get("color_hex") or None
    if color_hex and str(color_hex).lower() in ("null", "none", ""):
        color_hex = None

    return {
        "weapons":          ai_params.get("weapons",     "sword_default"),
        "armor":            ai_params.get("armor",       "armor_default"),
        "tools":            ai_params.get("tools",       "tools_default"),
        "consumables":      ai_params.get("consumables", "consumables_default"),
        "sky":              ai_params.get("sky",         "sky_default"),
        "gui":              ai_params.get("gui",         "gui_default"),
        "sounds":           ai_params.get("sounds",      "sounds_default"),
        "particles":        ai_params.get("particles",   "particles_default"),
        "mainmenu":         ai_params.get("mainmenu",    "menu_default"),
        "color":            "color_custom" if color_hex else "color_white",
        "color_hex_custom": color_hex,
        "version":          version,
        "mode":             "ai",
        "detected_theme":   _detect_theme(ai_params),
    }


def _detect_theme(params: dict) -> str:
    w = params.get("weapons", "")
    if "dark"    in w or "403" in w: return "Dark"
    if "crystal" in w or "415" in w: return "Crystal"
    if "mythic"  in w or "393" in w: return "Mythic"
    if "retro"   in w or "388" in w: return "Retro"
    if "vortex"  in w or "394" in w: return "Vortex"
    if "classic" in w or "398" in w: return "Classic"
    if "mell"    in w:               return "Premium"
    return "AI"
