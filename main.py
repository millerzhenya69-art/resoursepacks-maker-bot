"""
Точка входа. Запуск: python main.py
"""
import asyncio
import logging
import os

from download_packs import ensure_packs
ensure_packs()
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN, RENDER_URL
from bot.database import init_db
from bot.handlers import main_router
from bot.services.ping import self_ping_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

os.makedirs(os.path.join(os.path.dirname(__file__), "temp"), exist_ok=True)

# Глобальный bot для webhook
_bot: Bot | None = None


async def ping_handler(request: web.Request) -> web.Response:
    return web.Response(text="pong")


async def start_web_server() -> None:
    app = web.Application()
    app.router.add_get("/ping",    ping_handler)
    app.router.add_get("/healthz", ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"HTTP-сервер запущен на порту {port}")


# ── Основная функция ──────────────────────────────────────

async def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env!")

    await init_db()
    logger.info("База данных инициализирована")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp.include_router(main_router)

    await start_web_server()

    if RENDER_URL:
        asyncio.create_task(self_ping_loop())

    logger.info("Бот запускается...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=False,
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.error(f"Polling error: {e}")
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        logger.info("Сессия закрыта")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
