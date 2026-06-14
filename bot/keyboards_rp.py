"""
Клавиатуры для пошагового диалога создания ресурспака.
Расширенная версия — поддержка брони, инструментов, еды/зелий.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.rp_catalog import (
    WEAPONS, SKIES, GUIS, SOUNDS, PARTICLES, MAINMENUS,
    ARMOR, TOOLS, CONSUMABLES, COLOR_PRESETS,
)


def _make_grid(items: list[dict], cb_prefix: str,
               cols: int = 2, back_cb: str = "create_rp") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = []
    for item in items:
        row.append(InlineKeyboardButton(
            text=item["label"],
            callback_data=f"{cb_prefix}:{item['key']}"
        ))
        if len(row) == cols:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=back_cb))
    return builder.as_markup()


def weapons_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(WEAPONS, "wp", cols=2, back_cb="create_rp")

def sky_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(SKIES, "sky", cols=2, back_cb="step_back")

def gui_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(GUIS, "gui", cols=2, back_cb="step_back")

def sounds_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(SOUNDS, "snd", cols=2, back_cb="step_back")

def particles_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(PARTICLES, "ptc", cols=2, back_cb="step_back")

def mainmenu_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(MAINMENUS, "mm", cols=2, back_cb="step_back")

def armor_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(ARMOR, "arm", cols=2, back_cb="step_back")

def tools_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(TOOLS, "tl", cols=2, back_cb="step_back")

def consumables_keyboard() -> InlineKeyboardMarkup:
    return _make_grid(CONSUMABLES, "con", cols=2, back_cb="step_back")

def color_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = []
    for item in COLOR_PRESETS:
        row.append(InlineKeyboardButton(
            text=item["label"],
            callback_data=f"clr:{item['key']}"
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="step_back"))
    return builder.as_markup()

def confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Собрать ресурспак!", callback_data="rp_confirm"),
        InlineKeyboardButton(text="✏️ Изменить",           callback_data="rp_edit"),
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="rp_cancel"))
    return builder.as_markup()

def skip_keyboard(back_cb: str = "step_back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="step_skip"),
        InlineKeyboardButton(text="◀️ Назад",      callback_data=back_cb),
    )
    return builder.as_markup()
