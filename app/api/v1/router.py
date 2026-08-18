"""Aggregates every v1 router into a single mount point."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.activity_logs.routers import router as activity_logs_router
from app.modules.auth.routers import oauth_router
from app.modules.auth.routers import router as auth_router
from app.modules.blogs.routers import router as blogs_router
from app.modules.categories.routers import category_type_router
from app.modules.categories.routers import router as categories_router
from app.modules.menus.routers import router as menus_router
from app.modules.permissions.routers import router as permissions_router
from app.modules.roles.routers import router as roles_router
from app.modules.settings.routers import router as settings_router
from app.modules.translations.routers import router as translations_router
from app.modules.users.routers import router as users_router

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth_router)
# After the fixed auth paths, so `/auth/me` is matched before `/auth/{provider}`.
api_router.include_router(oauth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(permissions_router)
api_router.include_router(category_type_router)
api_router.include_router(categories_router)
api_router.include_router(blogs_router)
api_router.include_router(menus_router)
api_router.include_router(settings_router)
api_router.include_router(translations_router)
api_router.include_router(activity_logs_router)
