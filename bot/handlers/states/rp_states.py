from aiogram.fsm.state import State, StatesGroup


class TemplateRP(StatesGroup):
    """11-шаговый диалог шаблонного режима."""
    weapons      = State()   # 1. оружие
    armor        = State()   # 2. броня
    tools        = State()   # 3. инструменты
    consumables  = State()   # 4. еда и зелья
    sky          = State()   # 5. небо
    gui          = State()   # 6. GUI/инвентарь
    sounds       = State()   # 7. звуки
    color        = State()   # 8. цвет тинта
    mainmenu     = State()   # 9. главное меню
    particles    = State()   # 10. партикли
    custom_wish  = State()   # 11. пожелание
    building     = State()   # сборка


class CustomRP(StatesGroup):
    version   = State()
    upload    = State()
    building  = State()


class AIRP(StatesGroup):
    version   = State()
    prompt    = State()
    building  = State()
