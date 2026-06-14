"""
Self-ping для Render: раз в 14 минут бот пингует сам себя,
чтобы бесплатный инстанс не засыпал.
"""
import asyncio
import logging

import aiohttp

from bot.config import RENDER_URL

logger = logging.getLogger(__name__)


async def self_ping_loop() -> None:
    """Запускается как фоновая задача при старте бота."""
    if not RENDER_URL:
        logger.info("RENDER_URL не задан — self-ping отключён (локальный запуск)")
        return

    ping_url = RENDER_URL.rstrip("/") + "/ping"
    logger.info(f"Self-ping запущен → {ping_url}")

    await asyncio.sleep(30)  # небольшая пауза при старте

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.debug(f"Ping → {resp.status}")
            except Exception as e:
                logger.warning(f"Ping ошибка: {e}")
            await asyncio.sleep(14 * 60)  # 14 минут
