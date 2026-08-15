from app.modules.auth.routers.auth import router
from app.modules.auth.routers.oauth import router as oauth_router

__all__ = ["oauth_router", "router"]
