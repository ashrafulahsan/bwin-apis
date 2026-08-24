from app.modules.support.routers.admin import router as admin_router
from app.modules.support.routers.ticket import router
from app.modules.support.routers.trainer import router as trainer_router

__all__ = ["admin_router", "router", "trainer_router"]
