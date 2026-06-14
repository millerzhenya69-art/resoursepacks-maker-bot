"""
Контекстный сборщик — анализирует пожелание и подбирает ассеты под тему.
Расширенная версия: поддержка брони, инструментов, еды/зелий.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

THEME_PROFILES = {
    "aggressive": {
        "keywords":    ["агрессив", "злой", "evil", "кровь", "blood", "fire", "огонь", "ярость", "rage"],
        "weapons":     "sword_pvp400",
        "armor":       "armor_pvp403",
        "tools":       "tools_pvp398",
        "consumables": "consumables_pvp398",
        "sky":         "sky_pvp415",
        "gui":         "gui_dark",
        "sounds":      "sounds_hit1",
        "particles":   "particles_pvp398",
        "mainmenu":    "menu_dark",
        "color_hex":   "FF2222",
    },
    "purple": {
        "keywords":    ["фиолет", "purple", "violet", "магия", "magic", "мистик", "мистический"],
        "weapons":     "sword_purple",
        "armor":       "armor_pvp411",
        "tools":       "tools_pvp405",
        "consumables": "consumables_pvp403",
        "sky":         "sky_purple",
        "gui":         "gui_purple",
        "sounds":      "sounds_pvp",
        "particles":   "particles_stars",
        "mainmenu":    "menu_pvp411",
        "color_hex":   "AA44FF",
    },
    "blue": {
        "keywords":    ["синий", "blue", "лёд", "ice", "холод", "cold", "вода", "water", "море", "ocean"],
        "weapons":     "sword_blue",
        "armor":       "armor_pvp412",
        "tools":       "tools_pvp411",
        "consumables": "consumables_pvp412",
        "sky":         "sky_dark",
        "gui":         "gui_blue",
        "sounds":      "sounds_hit2",
        "particles":   "particles_small",
        "mainmenu":    "menu_dark",
        "color_hex":   "2244FF",
    },
    "gold": {
        "keywords":    ["золот", "gold", "yellow", "жёлт", "премиум", "premium", "король", "king", "царь"],
        "weapons":     "sword_pvp415",
        "armor":       "armor_mell",
        "tools":       "tools_mell",
        "consumables": "consumables_mell",
        "sky":         "sky_pvp398",
        "gui":         "gui_mell",
        "sounds":      "sounds_mell",
        "particles":   "particles_stars",
        "mainmenu":    "menu_mell",
        "color_hex":   "FFD700",
    },
    "clean": {
        "keywords":    ["чист", "clean", "минимал", "minimal", "белый", "white", "простой", "ванил"],
        "weapons":     "sword_default",
        "armor":       "armor_default",
        "tools":       "tools_default",
        "consumables": "consumables_default",
        "sky":         "sky_white",
        "gui":         "gui_pvp414",
        "sounds":      "sounds_default",
        "particles":   "particles_none",
        "mainmenu":    "menu_clean",
        "color_hex":   "FFFFFF",
    },
    "green": {
        "keywords":    ["зелён", "green", "природ", "nature", "лес", "forest", "трава"],
        "weapons":     "sword_pvp403",
        "armor":       "armor_pvp400",
        "tools":       "tools_pvp400",
        "consumables": "consumables_pvp400",
        "sky":         "sky_pvp398",
        "gui":         "gui_dark",
        "sounds":      "sounds_pvp398",
        "particles":   "particles_small",
        "mainmenu":    "menu_pvp398",
        "color_hex":   "44FF44",
    },
    "pvp": {
        "keywords":    ["pvp", "пвп", "бой", "fight", "battle", "сражен", "война", "war"],
        "weapons":     "sword_pvp398",
        "armor":       "armor_pvp398",
        "tools":       "tools_pvp398",
        "consumables": "consumables_pvp398",
        "sky":         "sky_black",
        "gui":         "gui_pvp403",
        "sounds":      "sounds_pvp",
        "particles":   "particles_none",
        "mainmenu":    "menu_pvp403",
        "color_hex":   "FF4444",
    },
    "black": {
        "keywords":    ["чёрн", "black", "тёмн", "dark", "ночь", "night", "shadow", "тень"],
        "weapons":     "sword_pvp412",
        "armor":       "armor_pvp412",
        "tools":       "tools_pvp411",
        "consumables": "consumables_pvp403",
        "sky":         "sky_black",
        "gui":         "gui_dark",
        "sounds":      "sounds_hit1",
        "particles":   "particles_none",
        "mainmenu":    "menu_dark",
        "color_hex":   "222222",
    },
    "mell": {
        "keywords":    ["mell", "мелл", "премиум", "premium", "дорог", "топ", "лучш"],
        "weapons":     "sword_mell",
        "armor":       "armor_mell",
        "tools":       "tools_mell",
        "consumables": "consumables_mell",
        "sky":         "sky_pvp403",
        "gui":         "gui_mell",
        "sounds":      "sounds_mell",
        "particles":   "particles_mell",
        "mainmenu":    "menu_mell",
        "color_hex":   "FFD700",
    },
    "crystal": {
        "keywords":    ["кристалл", "crystal", "стекл", "glass", "прозрач", "transparent"],
        "weapons":     "sword_pvp415",
        "armor":       "armor_pvp405",
        "tools":       "tools_pvp405",
        "consumables": "consumables_pvp412",
        "sky":         "sky_white",
        "gui":         "gui_pvp415",
        "sounds":      "sounds_pvp405",
        "particles":   "particles_pvp412",
        "mainmenu":    "menu_pvp415",
        "color_hex":   "00FFFF",
    },
}

DEFAULT_PROFILE = {
    "weapons":     "sword_pvp398",
    "armor":       "armor_pvp398",
    "tools":       "tools_pvp398",
    "consumables": "consumables_pvp398",
    "sky":         "sky_black",
    "gui":         "gui_pvp403",
    "sounds":      "sounds_pvp",
    "particles":   "particles_none",
    "mainmenu":    "menu_pvp403",
    "color_hex":   "FF4444",
}

WEAPON_COLORS = {
    "sword_red":    ["красн", "red", "fire", "огонь", "кровь", "blood", "алый"],
    "sword_blue":   ["синий", "blue", "лёд", "ice", "синего"],
    "sword_purple": ["фиолет", "purple", "violet", "лилов"],
    "sword_green":  ["зелён", "green"],
    "sword_pvp415": ["золот", "gold", "жёлт", "yellow"],
    "sword_mell":   ["mell", "мелл", "премиум"],
    "sword_pvp412": ["чёрн", "black", "тёмн", "dark"],
}


def detect_theme(text: str) -> str:
    if not text:
        return "pvp"
    text_lower = text.lower()
    scores = {}
    for theme, profile in THEME_PROFILES.items():
        score = sum(1 for kw in profile["keywords"] if kw in text_lower)
        if score > 0:
            scores[theme] = score
    return max(scores, key=scores.get) if scores else "pvp"


def detect_weapon_color(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    for key, keywords in WEAPON_COLORS.items():
        if any(kw in t for kw in keywords):
            return key
    return None


def apply_context(params: dict) -> dict:
    context_text = " ".join(filter(None, [
        params.get("custom_wish", ""),
        params.get("color_label", ""),
        params.get("weapons_label", ""),
        params.get("sky_label", ""),
    ]))

    theme = detect_theme(context_text)
    profile = THEME_PROFILES.get(theme, DEFAULT_PROFILE)
    result = dict(params)

    # Оружие — отдельная логика с учётом явного цвета
    if not result.get("weapons") or result.get("weapons") == "default":
        wish = params.get("custom_wish", "")
        weapon_key = detect_weapon_color(wish)
        result["weapons"] = weapon_key or profile.get("weapons", DEFAULT_PROFILE["weapons"])
        if not result.get("weapons_label"):
            result["weapons_label"] = f"🎨 Авто ({theme})"

    # Все остальные параметры
    for key in ["armor", "tools", "consumables", "sky", "gui",
                "sounds", "particles", "mainmenu"]:
        if not result.get(key) or result.get(key) in ("default", None):
            result[key] = profile.get(key, DEFAULT_PROFILE.get(key))
            if not result.get(f"{key}_label"):
                result[f"{key}_label"] = f"🎨 Авто ({theme})"

    if not result.get("color_hex") or result.get("color_hex") == "FFFFFF":
        result["color_hex"] = profile.get("color_hex", "FF4444")

    result["detected_theme"] = theme
    logger.info(f"Context: theme='{theme}' weapons='{result['weapons']}' "
                f"wish='{params.get('custom_wish','')}'")
    return result


def get_search_queries(params: dict) -> dict[str, str]:
    theme  = params.get("detected_theme", "pvp")
    wish   = params.get("custom_wish", "")
    color  = params.get("color_label", "")
    return {
        "sword":    f"minecraft {theme} pvp sword texture {wish} {color}",
        "bow":      f"minecraft {theme} pvp bow texture",
        "crossbow": f"minecraft {theme} pvp crossbow texture",
        "gui":      f"minecraft {theme} pvp inventory gui texture dark",
        "sky":      f"minecraft {theme} pvp skybox environment texture",
        "particle": f"minecraft pvp critical hit particle {theme}",
        "armor":    f"minecraft {theme} pvp armor texture",
    }
