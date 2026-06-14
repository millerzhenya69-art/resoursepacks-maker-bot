"""
RP Builder — оптимизированная сборка рп.

Ключевые оптимизации:
- Извлекаем из base ZIP только нужные папки (не всё подряд)
- Тинт через ImageChops.multiply (векторный, не попиксельный)
- Веб-поиск с таймаутом 5с чтобы не тормозить
- Прогресс-колбэк для обновления сообщения в Telegram
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import zipfile
from typing import Optional, Callable, Awaitable

from bot.config import PACKS_DIR, TEMP_DIR
from bot.services.rp_catalog import (
    PACK_FORMATS, WEAPONS, SKIES, GUIS, SOUNDS, PARTICLES, MAINMENUS,
    ARMOR, TOOLS, CONSUMABLES,
)
from bot.services.context_builder import apply_context, get_search_queries
from bot.services.texture_search import search_and_download_texture, is_valid_png

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates"
)

# Иконка пака — лежит рядом с этим файлом в bot/services/
PACK_ICON_PATH = os.path.join(os.path.dirname(__file__), "pack_icon.png")

CATALOG_MAP = {
    "weapons":     WEAPONS,
    "armor":       ARMOR,
    "tools":       TOOLS,
    "consumables": CONSUMABLES,
    "sky":         SKIES,
    "gui":         GUIS,
    "sounds":      SOUNDS,
    "particles":   PARTICLES,
    "mainmenu":    MAINMENUS,
}

# Только эти папки берём из базового архива
NEEDED_PREFIXES = (
    "assets/minecraft/textures/item/",
    "assets/minecraft/textures/environment/",
    "assets/minecraft/textures/gui/",
    "assets/minecraft/textures/particle/",
    "assets/minecraft/textures/entity/",
    "assets/minecraft/textures/models/armor/",
    "assets/minecraft/models/item/",
    "assets/minecraft/sounds/",
)

SKIP_PREFIXES = (
    "assets/minecraft/optifine/",
    "assets/minecraft/shaders/",
    # Панорамы главного меню — очень тяжёлые (~500KB каждая), не нужны для PvP
    "assets/minecraft/textures/gui/title/panorama",
    "assets/minecraft/textures/gui/title/background/panorama",
)

# Маппинг старых имён файлов (1.12 era) → новые (1.13+)
_LEGACY_RENAMES = {
    # Еда
    "apple_golden.png":              "golden_apple.png",
    "enchanted_golden_apple.png":    "enchanted_golden_apple.png",  # без изменений
    "potion_bottle_drinkable.png":   "potion.png",
    "potion_bottle_empty.png":       "glass_bottle.png",
    "potion_bottle_overlay.png":     "potion_overlay.png",
    "potion_bottle_splash.png":      "splash_potion.png",
    # Броня (старые имена)
    "gold_boots.png":               "golden_boots.png",
    "gold_chestplate.png":          "golden_chestplate.png",
    "gold_helmet.png":              "golden_helmet.png",
    "gold_leggings.png":            "golden_leggings.png",
    "gold_axe.png":                 "golden_axe.png",
    "gold_hoe.png":                 "golden_hoe.png",
    "gold_pickaxe.png":             "golden_pickaxe.png",
    "gold_shovel.png":              "golden_shovel.png",
    "gold_sword.png":               "golden_sword.png",
    "gold_nugget.png":              "gold_nugget.png",
}

def _fix_double_path(arc: str) -> str:
    """
    Исправляет двойные пути вида:
      assets/minecraft/textures/item/assets/minecraft/textures/items/X.png
    → assets/minecraft/textures/item/X.png

    Также переименовывает legacy (1.12-era) имена файлов в современные.
    """
    DOUBLE = "assets/minecraft/textures/item/assets/minecraft/textures/items/"
    if DOUBLE in arc.replace("\\", "/"):
        basename = arc.split("/")[-1]
        # Переименовываем legacy файлы
        basename = _LEGACY_RENAMES.get(basename, basename)
        return f"assets/minecraft/textures/item/{basename}"
    return arc

ProgressCallback = Callable[[str], Awaitable[None]]


class RPBuilder:

    def __init__(self, user_id: int, version: str, params: dict):
        self.user_id      = user_id
        self.version      = version
        self.params       = params
        self.work_dir     = os.path.join(TEMP_DIR, f"rp_{user_id}_{int(time.time())}")
        self.out_zip      = os.path.join(TEMP_DIR, f"rp_{user_id}_{version}_{int(time.time())}.zip")
        self.web_searched = 0
        self._progress_cb: Optional[ProgressCallback] = None

    def set_progress_callback(self, cb: ProgressCallback):
        self._progress_cb = cb

    async def _progress(self, text: str):
        if self._progress_cb:
            try:
                await self._progress_cb(text)
            except Exception:
                pass

    async def build(self) -> Optional[str]:
        t0 = time.time()
        try:
            self.params = apply_context(self.params)
            theme = self.params.get("detected_theme", "pvp")
            logger.info(f"Building RP: user={self.user_id} ver={self.version} theme={theme}")

            loop = asyncio.get_event_loop()

            await self._progress("📦 Распаковка базового рп...")
            await loop.run_in_executor(None, self._extract_needed_only)

            await self._progress("🎨 Наложение шаблонов...")
            await loop.run_in_executor(None, self._apply_templates)

            await self._progress("🌐 Поиск текстур...")
            await asyncio.wait_for(self._fill_missing_textures(), timeout=20.0)

            await self._progress("✨ Применение цвета и упаковка...")
            await loop.run_in_executor(None, self._finalize_sync)

            elapsed = time.time() - t0
            logger.info(f"RP built in {elapsed:.1f}s, zip={os.path.getsize(self.out_zip)/1024/1024:.1f}MB")
            return self.out_zip

        except asyncio.TimeoutError:
            logger.warning("Web search timed out — continuing without it")
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._finalize_sync)
                return self.out_zip
            except Exception as e:
                logger.error(f"Finalize error after timeout: {e}")
                self.cleanup()
                return None
        except Exception as e:
            logger.error(f"RPBuilder error: {e}", exc_info=True)
            self.cleanup()
            return None

    # ── Извлечение только нужных файлов ──────────────────────

    def _extract_needed_only(self):
        os.makedirs(self.work_dir, exist_ok=True)
        base_zip = os.path.join(PACKS_DIR, f"base_{self.version}.zip")

        if not os.path.exists(base_zip):
            logger.warning(f"Base pack not found: {base_zip}")
            self._create_minimal_structure()
            return

        extracted = 0
        with zipfile.ZipFile(base_zip, "r") as zf:
            for member in zf.infolist():
                name = member.filename
                if name.endswith("/"):
                    continue
                if not any(name.startswith(p) for p in NEEDED_PREFIXES):
                    if name not in ("pack.mcmeta", "pack.png"):
                        continue
                dest = os.path.join(self.work_dir, name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                extracted += 1

        logger.info(f"Extracted {extracted} files from base pack {self.version}")

    def _create_minimal_structure(self):
        base = os.path.join(self.work_dir, "assets", "minecraft")
        for sub in ["textures/item", "textures/environment",
                    "textures/gui/container", "textures/particle",
                    "sounds/entity/player/attack", "sounds/entity/player/hurt",
                    "models/item"]:
            os.makedirs(os.path.join(base, sub), exist_ok=True)

    # ── Шаблоны ───────────────────────────────────────────────

    def _apply_templates(self):
        for param_name, catalog in CATALOG_MAP.items():
            chosen_key = self.params.get(param_name)
            if not chosen_key:
                continue
            item = next((i for i in catalog if i["key"] == chosen_key), None)
            if not item:
                continue
            src = os.path.join(TEMPLATES_DIR, item["folder"])
            if os.path.isdir(src):
                self._copy_tree(src, self.work_dir)

        self._generate_sounds_json()

    def _copy_tree(self, src: str, dst: str):
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            tgt = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(tgt, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(tgt, f)
                arc = os.path.relpath(dst_file, self.work_dir).replace("\\", "/")
                if any(arc.startswith(skip) for skip in SKIP_PREFIXES):
                    continue
                # Исправляем двойные пути: textures/item/assets/minecraft/textures/items/X
                # → textures/item/X  (старый формат 1.12 era)
                arc_fixed = _fix_double_path(arc)
                if arc_fixed != arc:
                    dst_file = os.path.join(self.work_dir, arc_fixed)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)

    def _generate_sounds_json(self):
        sounds_dir = os.path.join(
            self.work_dir, "assets", "minecraft", "sounds", "entity", "player"
        )
        if not os.path.isdir(sounds_dir):
            return

        sounds_json = {}
        event_map = {
            "attack": [
                ("crit",      "entity.player.attack.crit"),
                ("strong",    "entity.player.attack.strong"),
                ("weak",      "entity.player.attack.weak"),
                ("knockback", "entity.player.attack.knockback"),
                ("sweep",     "entity.player.attack.sweep"),
            ],
            "hurt": [
                ("hurt",     "entity.player.hurt"),
                ("freeze",   "entity.player.hurt_freeze"),
                ("fire",     "entity.player.hurt_on_fire"),
            ],
        }

        for subdir, events in event_map.items():
            sub_path = os.path.join(sounds_dir, subdir)
            if not os.path.isdir(sub_path):
                continue
            ogg_files = sorted(f for f in os.listdir(sub_path) if f.endswith(".ogg"))
            if not ogg_files:
                continue

            for fname in ogg_files:
                name = fname.replace(".ogg", "").lower()
                matched = events[0][1]
                for key, event in events:
                    if key in name:
                        matched = event
                        break
                sound_path = f"entity/player/{subdir}/{fname.replace('.ogg','')}"
                if matched not in sounds_json:
                    sounds_json[matched] = {"sounds": [], "replace": True}
                sounds_json[matched]["sounds"].append({"name": sound_path, "volume": 1.0})

        if sounds_json:
            mc_dir = os.path.join(self.work_dir, "assets", "minecraft")
            with open(os.path.join(mc_dir, "sounds.json"), "w", encoding="utf-8") as f:
                json.dump(sounds_json, f, indent=2)
            logger.info(f"Generated sounds.json: {len(sounds_json)} events")

    # ── Финализация ───────────────────────────────────────────

    def _finalize_sync(self):
        color_hex = self.params.get("color_hex", "")
        if color_hex and color_hex.upper() not in ("FFFFFF", ""):
            self._apply_tint(color_hex)
        self._inject_pack_icon()        # иконка пака
        self._inject_armor_trims()      # Equipment JSON для 1.21.2+
        self._inject_sky_compat()       # небо — копируем в celestial/ для 1.21.2+
        self._update_mcmeta()
        self._pack_zip()

    # ── #5 Иконка пака ────────────────────────────────────────

    def _inject_pack_icon(self):
        """Копирует pack.png (128x128) в корень пака."""
        if os.path.exists(PACK_ICON_PATH):
            dst = os.path.join(self.work_dir, "pack.png")
            shutil.copy2(PACK_ICON_PATH, dst)

    # ── #4 Броня и небо — Equipment API (1.21.2+) ─────────────

    def _inject_armor_trims(self):
        """
        В Minecraft 1.21.2+ броня отображается через систему Equipment.
        Нужно создать JSON-файлы в assets/minecraft/equipment/
        которые указывают на наши текстуры из textures/models/armor/.

        Без этих файлов текстуры брони из models/armor/ есть в архиве,
        но игра не применяет их — отсюда "фантомный" эффект.
        """
        armor_tex_dir = os.path.join(
            self.work_dir, "assets", "minecraft", "textures", "models", "armor"
        )
        if not os.path.isdir(armor_tex_dir):
            return

        # Проверяем наличие хотя бы одной текстуры брони
        armor_files = [f for f in os.listdir(armor_tex_dir) if f.endswith(".png")]
        if not armor_files:
            return

        equipment_dir = os.path.join(
            self.work_dir, "assets", "minecraft", "equipment"
        )
        os.makedirs(equipment_dir, exist_ok=True)

        # Маппинг тип_брони → имена layer файлов
        # layer_1 = основная броня, layer_2 = штаны
        ARMOR_EQUIPMENT = {
            "diamond":     ("diamond_layer_1",    "diamond_layer_2"),
            "iron":        ("iron_layer_1",        "iron_layer_2"),
            "gold":        ("gold_layer_1",        "gold_layer_2"),
            "netherite":   ("netherite_layer_1",   "netherite_layer_2"),
            "chainmail":   ("chainmail_layer_1",   "chainmail_layer_2"),
            "leather":     ("leather_layer_1",     "leather_layer_2"),
            "turtle_scute": ("turtle_layer_1",     None),
        }

        created = 0
        for material, (layer1, layer2) in ARMOR_EQUIPMENT.items():
            # Проверяем что у нас есть эти текстуры
            has_layer1 = os.path.exists(os.path.join(armor_tex_dir, f"{layer1}.png"))
            if not has_layer1:
                continue

            equipment_json: dict = {
                "layers": [
                    {
                        "texture": f"minecraft:{layer1}"
                    }
                ]
            }

            # Добавляем второй слой если есть
            if layer2 and os.path.exists(os.path.join(armor_tex_dir, f"{layer2}.png")):
                equipment_json["layers"].append({
                    "texture": f"minecraft:{layer2}",
                    "dyeable": material == "leather"  # только кожа красится
                })

            out_path = os.path.join(equipment_dir, f"{material}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(equipment_json, f, indent=2)
            created += 1

        if created:
            logger.info(f"Injected {created} equipment JSON files for armor (1.21.2+)")

        # Также добавляем elytra в equipment если есть текстура
        elytra_tex = os.path.join(armor_tex_dir, "elytra.png")
        if os.path.exists(elytra_tex):
            elytra_json = {"layers": [{"texture": "minecraft:elytra"}]}
            with open(os.path.join(equipment_dir, "elytra.json"), "w") as f:
                json.dump(elytra_json, f, indent=2)

    def _inject_sky_compat(self):
        """
        В Minecraft 1.21.2+ солнце и луна переехали в:
          textures/environment/celestial/sun.png
          textures/environment/celestial/moon/full_moon.png (и т.д.)

        Если шаблон положил файлы по старому пути (sun.png, moon_phases.png),
        копируем их в новые пути чтобы небо отображалось корректно.
        """
        env_dir = os.path.join(self.work_dir, "assets", "minecraft", "textures", "environment")
        if not os.path.isdir(env_dir):
            return

        celestial_dir = os.path.join(env_dir, "celestial")
        moon_dir      = os.path.join(celestial_dir, "moon")

        # Солнце: sun.png → celestial/sun.png
        old_sun = os.path.join(env_dir, "sun.png")
        new_sun = os.path.join(celestial_dir, "sun.png")
        if os.path.exists(old_sun) and not os.path.exists(new_sun):
            os.makedirs(celestial_dir, exist_ok=True)
            shutil.copy2(old_sun, new_sun)
            logger.info("Copied sun.png → celestial/sun.png")

        # Луна: moon_phases.png (старый атлас 4x2) → 8 отдельных файлов
        # В 1.21.2+ луна разбита на 8 фаз в папке celestial/moon/
        old_moon = os.path.join(env_dir, "moon_phases.png")
        if os.path.exists(old_moon):
            moon_phases = [
                "full_moon", "waning_gibbous", "third_quarter", "waning_crescent",
                "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous"
            ]
            os.makedirs(moon_dir, exist_ok=True)
            # Разрезаем атлас 4x2 на 8 отдельных PNG
            try:
                from PIL import Image
                atlas = Image.open(old_moon)
                w, h = atlas.size
                fw, fh = w // 4, h // 2
                for i, phase in enumerate(moon_phases):
                    dest_phase = os.path.join(moon_dir, f"{phase}.png")
                    if not os.path.exists(dest_phase):
                        col, row = i % 4, i // 4
                        frame = atlas.crop((col*fw, row*fh, (col+1)*fw, (row+1)*fh))
                        frame.save(dest_phase, "PNG")
                logger.info(f"Split moon_phases.png into 8 celestial/moon/ files")
            except Exception as e:
                logger.warning(f"Moon split failed: {e} — copying full atlas as full_moon")
                shutil.copy2(old_moon, os.path.join(moon_dir, "full_moon.png"))

        # Облака: clouds.png остаётся на том же месте — никаких изменений не нужно

    def _apply_tint(self, hex_color: str):
        """Тинт ТОЛЬКО на оружие — строгий список имён файлов."""
        try:
            from PIL import Image, ImageChops
            item_dir = os.path.join(self.work_dir, "assets", "minecraft", "textures", "item")
            if not os.path.isdir(item_dir):
                return

            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)

            WEAPON_NAMES = {
                "wooden_sword", "stone_sword", "iron_sword",
                "golden_sword", "diamond_sword", "netherite_sword",
                "wooden_axe", "stone_axe", "iron_axe",
                "golden_axe", "diamond_axe", "netherite_axe",
                "bow", "crossbow", "trident",
                "bow_pulling_0", "bow_pulling_1", "bow_pulling_2",
                "crossbow_pulling_0", "crossbow_pulling_1", "crossbow_pulling_2",
                "crossbow_arrow", "crossbow_firework",
            }
            tinted = 0
            for fname in os.listdir(item_dir):
                if not fname.endswith(".png"):
                    continue
                if fname[:-4].lower() not in WEAPON_NAMES:
                    continue
                fpath = os.path.join(item_dir, fname)
                if not is_valid_png(fpath):
                    continue
                try:
                    img = Image.open(fpath).convert("RGBA")
                    _, _, _, a_ch = img.split()
                    color_layer = Image.new("RGB", img.size, (r, g, b))
                    tinted_rgb  = ImageChops.multiply(img.convert("RGB"), color_layer)
                    out = tinted_rgb.convert("RGBA")
                    out.putalpha(a_ch)
                    out.save(fpath, "PNG", optimize=False)
                    tinted += 1
                except Exception:
                    pass
            if tinted:
                logger.info(f"Tinted {tinted} weapon textures with #{hex_color}")
        except ImportError:
            pass

    # ── #7 pack_format ────────────────────────────────────────

    def _update_mcmeta(self):
        fmt  = PACK_FORMATS.get(self.version, {"pack_format": 46})
        name = self.params.get("rp_name", f"PvP Pack {self.version} by unkony")
        theme = self.params.get("detected_theme", "")
        if theme:
            name += f" [{theme}]"

        pack_format = fmt["pack_format"]

        # supported_formats позволяет паку работать в диапазоне версий
        # что снижает количество предупреждений "несовместим"
        mcmeta = {
            "pack": {
                "pack_format": pack_format,
                "supported_formats": _get_supported_formats(pack_format),
                "description": name,
            }
        }
        with open(os.path.join(self.work_dir, "pack.mcmeta"), "w", encoding="utf-8") as f:
            json.dump(mcmeta, f, indent=2, ensure_ascii=False)

    def _pack_zip(self):
        with zipfile.ZipFile(self.out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, dirs, files in os.walk(self.work_dir):
                for file in files:
                    fp = os.path.join(root, file)
                    arc = os.path.relpath(fp, self.work_dir)
                    # PNG уже содержат внутреннее сжатие, но ZIP DEFLATE
                    # дополнительно снижает размер архива ещё на 20-40%
                    zf.write(fp, arc, compress_type=zipfile.ZIP_DEFLATED)
        size = os.path.getsize(self.out_zip) / 1024 / 1024
        logger.info(f"Packed ZIP: {size:.1f} MB")

    # ── Веб-поиск ─────────────────────────────────────────────

    async def _fill_missing_textures(self):
        queries  = get_search_queries(self.params)
        item_dir = os.path.join(self.work_dir, "assets", "minecraft", "textures", "item")
        os.makedirs(item_dir, exist_ok=True)

        tasks = []
        for category, filenames in [
            ("sword", ["diamond_sword.png", "netherite_sword.png"]),
            ("bow",   ["bow.png"]),
        ]:
            query = queries.get(category, f"minecraft pvp {category} texture")
            for fname in filenames:
                dest = os.path.join(item_dir, fname)
                if os.path.exists(dest) and is_valid_png(dest):
                    continue
                tasks.append(search_and_download_texture(query, category, item_dir, fname))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.web_searched = sum(1 for r in results if r is True)
            if self.web_searched:
                logger.info(f"Web: found {self.web_searched} textures")

    # ── Очистка ───────────────────────────────────────────────

    def cleanup(self):
        try:
            if os.path.isdir(self.work_dir):
                shutil.rmtree(self.work_dir)
        except Exception:
            pass

    def cleanup_zip(self):
        try:
            if os.path.isfile(self.out_zip):
                os.remove(self.out_zip)
        except Exception:
            pass

    @property
    def stats(self) -> dict:
        return {
            "theme":     self.params.get("detected_theme", "pvp"),
            "web_found": self.web_searched,
            "version":   self.version,
        }


def _get_supported_formats(pack_format: int) -> list[int]:
    """
    Широкий диапазон совместимости — охватывает все версии 1.21.x
    включая снапшоты и pre-release с неизвестным pack_format.
    34 = 1.21/1.21.1, 999 = любой будущий снапшот.
    """
    return [34, 999]


async def cleanup_old_temp(max_age_seconds: int = 3600):
    now = time.time()
    if not os.path.isdir(TEMP_DIR):
        return
    for name in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, name)
        try:
            if os.path.getmtime(path) < now - max_age_seconds:
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        except Exception:
            pass
