"""Aggregates every v1 router into a single mount point."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.activity_logs.routers import router as activity_logs_router
from app.modules.auth.routers import oauth_router
from app.modules.auth.routers import router as auth_router
from app.modules.automations.routers import router as automations_router
from app.modules.blogs.routers import router as blogs_router
from app.modules.categories.routers import category_type_router
from app.modules.categories.routers import router as categories_router
from app.modules.consultancies.routers import router as consultancies_router
from app.modules.courses.routers import router as courses_router
from app.modules.master_cruds.routers import master_crud_field_router
from app.modules.master_cruds.routers import router as master_cruds_router
from app.modules.menus.routers import router as menus_router
from app.modules.pages.routers import router as pages_router
from app.modules.permissions.routers import router as permissions_router
from app.modules.roles.routers import router as roles_router
from app.modules.settings.routers import router as settings_router
from app.modules.subscriptions.routers import newsletter_router
from app.modules.subscriptions.routers import router as subscriptions_router
from app.modules.support.routers import admin_router as support_admin_router
from app.modules.support.routers import router as support_router
from app.modules.support.routers import trainer_router as support_trainer_router
from app.modules.translations.routers import router as translations_router
from app.modules.users.routers import router as users_router
from app.modules.users.routers.user_details import router as user_details_router

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth_router)
# After the fixed auth paths, so `/auth/me` is matched before `/auth/{provider}`.
api_router.include_router(oauth_router)
api_router.include_router(users_router)
api_router.include_router(user_details_router)
api_router.include_router(roles_router)
api_router.include_router(permissions_router)
api_router.include_router(category_type_router)
api_router.include_router(categories_router)
api_router.include_router(automations_router)
api_router.include_router(consultancies_router)
api_router.include_router(courses_router)
api_router.include_router(blogs_router)
api_router.include_router(pages_router)
api_router.include_router(menus_router)
api_router.include_router(master_crud_field_router)
api_router.include_router(master_cruds_router)
api_router.include_router(settings_router)
api_router.include_router(subscriptions_router)
# Public signup, confirm and unsubscribe. Separate from the guarded
# `/subscriptions` router above precisely so nothing there is an exception.
api_router.include_router(newsletter_router)
# The admin and trainer routers first: their paths are fixed, and
# `/support/tickets/{ticket_id}` in the shared router would otherwise
# swallow `/support/my-tickets` and `/support/admin/tickets`.
api_router.include_router(support_admin_router)
api_router.include_router(support_trainer_router)
api_router.include_router(support_router)
api_router.include_router(translations_router)
api_router.include_router(activity_logs_router)
