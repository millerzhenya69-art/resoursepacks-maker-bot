"""
Скачивает базовые паки если их нет на диске.
Запускается автоматически при старте бота.
"""
import os
import urllib.request
import logging

logger = logging.getLogger(__name__)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
PACKS_DIR = os.path.join(BASE_DIR, "packs", "base")

# ── Замени URL на свои прямые ссылки скачивания ───────────
# Рекомендую: Google Drive → "Открыть доступ всем" → скопировать ID файла
# Прямая ссылка: https://drive.google.com/uc?export=download&id=FILE_ID
PACKS = {
    "base_1.21.4.zip":  os.getenv("PACK_URL_1214", ""),
    "base_1.21.8.zip":  os.getenv("PACK_URL_1218", ""),
    "base_1.21.11.zip": os.getenv("PACK_URL_12111", ""),
}


def ensure_packs() -> None:
    """Проверяет наличие базовых паков и скачивает недостающие."""
    os.makedirs(PACKS_DIR, exist_ok=True)

    for filename, url in PACKS.items():
        dest = os.path.join(PACKS_DIR, filename)

        if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
            logger.info(f"Pack OK: {filename}")
            continue

        if not url:
            logger.warning(
                f"URL not set for {filename}. "
                f"Set env var PACK_URL_1214 / PACK_URL_1218 / PACK_URL_12111"
            )
            continue

        logger.info(f"Downloading {filename} from {url[:60]}...")
        try:
            # Для Google Drive нужен особый заголовок
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=300) as response:
                with open(dest, "wb") as f:
                    f.write(response.read())
            size_mb = os.path.getsize(dest) / 1024 / 1024
            logger.info(f"Downloaded {filename} ({size_mb:.1f} MB)")
        except Exception as e:
            logger.error(f"Failed to download {filename}: {e}")
            if os.path.exists(dest):
                os.remove(dest)
