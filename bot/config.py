import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

# ── Каналы для обязательной подписки ──────────────────────
REQUIRED_CHANNELS = [
    {"username": "unkonyy",           "title": "unkonyy",           "url": "https://t.me/unkonyy"},
    {"username": "AI_Elyon",          "title": "AI Elyon",          "url": "https://t.me/AI_Elyon"},
    {"username": "Elyon_by_unkony_bot","title": "@Elyon_by_unkony_bot","url": "https://t.me/Elyon_by_unkony_bot"},
]

# ── Генерации ──────────────────────────────────────────────
FREE_GENERATIONS: int = 3          # бесплатных при старте
REFERRAL_BONUS: int = 2            # бонус за каждого приглашённого

# ── Тарифы (Stars → кол-во генераций) ─────────────────────
TARIFFS = {
    "start":   {"gens": 10,  "stars": 1,  "rub": 91},
    "basic":   {"gens": 20,  "stars": 150, "rub": 182},
    "pro":     {"gens": 50,  "stars": 350, "rub": 420},
    "ai_pack": {"gens": 5,   "stars": 0, "rub": 240},  # 5 ИИ-генераций
}
# Цена 1 генерации в звёздах (для кастомного кол-ва)
STARS_PER_GEN: float = 7.5
RUBLES_PER_GEN: float = 9.1

# ── Версии ресурспаков ─────────────────────────────────────
RP_VERSIONS = ["1.21.4", "1.21.8", "1.21.11"]

# ── Пути ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(BASE_DIR, "packs", "base")
TEMP_DIR  = os.path.join(BASE_DIR, "temp")

# ── Платёжные системы ─────────────────────────────────────
CRYPTOBOT_TOKEN: str  = os.getenv("CRYPTOBOT_TOKEN", "")
DONATEPAY_API_KEY: str = os.getenv("DONATEPAY_API_KEY", "")
DONATEPAY_WEBHOOK_SECRET: str = os.getenv("DONATEPAY_WEBHOOK_SECRET", "")

# ── Прочее ────────────────────────────────────────────────
RENDER_URL: str   = os.getenv("RENDER_URL", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Форум для публикации РП ───────────────────────────────
FORUM_CHANNEL: str = os.getenv("FORUM_CHANNEL", "forum_of_resoursepack_maker")  # username без @
