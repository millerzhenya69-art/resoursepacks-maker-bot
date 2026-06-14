"""
Поиск и загрузка текстур из интернета.
Источники: GitHub (open-source рп), Planet Minecraft API, прямые URL.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Известные open-source PvP рп на GitHub (только репозитории без ограничений)
GITHUB_SOURCES = [
    # format: (repo, branch, assets_path)
    ("FurfSky-Reborn/FurfSky-Reborn", "main",   "src/main/resources/assets"),
    ("robotkoer/invictus",            "master",  "assets"),
    ("dokucraft/dokucraft-light",     "master",  "assets"),
]

# Заголовки для имитации браузера
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "image/png,image/*,*/*",
}

TIMEOUT = aiohttp.ClientTimeout(total=15)


async def search_and_download_texture(
    query: str,
    category: str,
    dest_dir: str,
    filename: str,
) -> bool:
    """
    Ищет текстуру по запросу и скачивает в dest_dir/filename.
    Возвращает True если успешно.

    query    — описание (например "purple pvp sword minecraft texture")
    category — "sword" | "bow" | "sky" | "gui" | "particle"
    dest_dir — куда сохранить
    filename — имя файла (например "diamond_sword.png")
    """
    os.makedirs(dest_dir, exist_ok=True)

    # Пробуем источники по приоритету
    strategies = [
        _try_github_raw(category, filename, dest_dir),
        _try_planet_minecraft(query, dest_dir, filename),
        _try_direct_minecraft_wiki(filename, dest_dir),
    ]

    for strategy in strategies:
        try:
            result = await strategy
            if result:
                logger.info(f"Downloaded texture: {filename} for query '{query}'")
                return True
        except Exception as e:
            logger.debug(f"Strategy failed for {filename}: {e}")

    logger.warning(f"Could not find texture: {filename} (query: {query})")
    return False


async def _try_github_raw(category: str, filename: str, dest_dir: str) -> bool:
    """Пробует скачать текстуру из известных GitHub репозиториев."""
    # Маппинг категорий на пути в рп
    path_map = {
        "sword":     "minecraft/textures/item",
        "bow":       "minecraft/textures/item",
        "crossbow":  "minecraft/textures/item",
        "gui":       "minecraft/textures/gui/container",
        "sky":       "minecraft/textures/environment",
        "particle":  "minecraft/textures/particle",
    }
    asset_path = path_map.get(category, "minecraft/textures/item")

    async with aiohttp.ClientSession(headers=HEADERS, timeout=TIMEOUT) as session:
        for repo, branch, base in GITHUB_SOURCES:
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/{base}/{asset_path}/{filename}"
            try:
                async with session.get(url) as r:
                    if r.status == 200 and "image" in r.headers.get("content-type", ""):
                        data = await r.read()
                        if len(data) > 100:  # не пустой файл
                            dest = os.path.join(dest_dir, filename)
                            with open(dest, "wb") as f:
                                f.write(data)
                            return True
            except Exception:
                continue
    return False


async def _try_planet_minecraft(query: str, dest_dir: str, filename: str) -> bool:
    """Ищет рп на Planet Minecraft и скачивает нужную текстуру."""
    # Planet Minecraft не имеет открытого API для текстур — пропускаем
    # В будущем можно добавить парсинг
    return False


async def _try_direct_minecraft_wiki(filename: str, dest_dir: str) -> bool:
    """Скачивает ванильную текстуру с minecraft.wiki как запасной вариант."""
    # Убираем расширение для построения URL
    name = filename.replace(".png", "").replace("_", " ").title().replace(" ", "_")
    url = f"https://minecraft.wiki/images/{name}.png"

    async with aiohttp.ClientSession(headers=HEADERS, timeout=TIMEOUT) as session:
        try:
            async with session.get(url) as r:
                if r.status == 200:
                    data = await r.read()
                    if len(data) > 100:
                        dest = os.path.join(dest_dir, filename)
                        with open(dest, "wb") as f:
                            f.write(data)
                        return True
        except Exception:
            pass
    return False


async def download_pvp_pack_from_github(
    dest_zip: str,
    theme: str = "default",
) -> bool:
    """
    Скачивает готовый PvP рп с GitHub как основу для генерации.
    theme: "purple" | "red" | "blue" | "default"
    """
    # Список проверенных открытых PvP рп
    pack_urls = {
        "default": "https://github.com/robotkoer/invictus/archive/refs/heads/master.zip",
        "purple":  "https://github.com/robotkoer/invictus/archive/refs/heads/master.zip",
        "red":     "https://github.com/robotkoer/invictus/archive/refs/heads/master.zip",
    }
    url = pack_urls.get(theme, pack_urls["default"])

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.get(url) as r:
                if r.status == 200:
                    data = await r.read()
                    with open(dest_zip, "wb") as f:
                        f.write(data)
                    return True
    except Exception as e:
        logger.error(f"Failed to download pack: {e}")
    return False


# ── Утилиты ───────────────────────────────────────────────

def is_valid_png(path: str) -> bool:
    """Проверяет что файл является валидным PNG."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
            return header[:8] == b'\x89PNG\r\n\x1a\n'
    except Exception:
        return False


def get_minecraft_texture_names(category: str) -> list[str]:
    """Возвращает список имён файлов текстур для категории."""
    names = {
        "sword": [
            "wooden_sword.png", "stone_sword.png", "iron_sword.png",
            "golden_sword.png", "diamond_sword.png", "netherite_sword.png",
        ],
        "bow": [
            "bow.png", "bow_pulling_0.png", "bow_pulling_1.png", "bow_pulling_2.png",
        ],
        "crossbow": [
            "crossbow.png", "crossbow_arrow.png",
            "crossbow_pulling_0.png", "crossbow_pulling_1.png", "crossbow_pulling_2.png",
        ],
        "gui": [
            "inventory.png", "container/generic_54.png",
        ],
        "sky": [
            "sun.png", "moon_phases.png",
        ],
        "particle": [
            "critical_hit.png", "magic_critical_hit.png",
        ],
    }
    return names.get(category, [])
