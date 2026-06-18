from aiogram import Router
from .start       import router as start_router
from .create_rp   import router as create_rp_router
from .template_rp import router as template_rp_router
from .custom_rp   import router as custom_rp_router
from .ai_rp       import router as ai_rp_router
from .upgrade     import router as upgrade_router
from .payment     import router as payment_router
from .admin       import router as admin_router

main_router = Router()
main_router.include_routers(
    start_router,
    create_rp_router,
    template_rp_router,
    custom_rp_router,
    ai_rp_router,
    payment_router,
    upgrade_router,
    admin_router,   # admin последним — его FSM не должен перехватывать чужие апдейты
)
