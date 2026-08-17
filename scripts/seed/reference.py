"""Roles, permissions, their default grants, settings and translations.

The one seeder that is not demo data. Every environment wants this, including
production, and most of it is applied by migration as well - so a run here
usually reports zeroes and exists to fill gaps: a locale added since the last
deployment, a setting a migration never knew about.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.services.role import RoleService
from app.modules.settings.services.setting import SettingService
from app.modules.translations.services.translation import TranslationService
from scripts.seed.base import Seeder, SeedOptions


async def seed_reference_data(session: AsyncSession) -> dict[str, int]:
    """Roles, permissions, default grants, settings and translations."""
    roles = await RoleService(session).seed_system_roles()

    permissions = PermissionService(session)
    created_permissions = await permissions.seed_system_permissions()
    grants = await permissions.seed_default_role_permissions()

    settings_created = await SettingService(session).seed_system_settings()

    translations = await TranslationService(session).sync_all_locales()

    return {
        "roles": roles,
        "permissions": created_permissions,
        "roles_granted": len(grants),
        "settings": settings_created,
        "translations": sum(translations.values()),
    }


class ReferenceSeeder(Seeder):
    name = "reference"
    description = "Roles, permissions, default grants, settings, translations."

    async def run(self, session: AsyncSession, options: SeedOptions) -> dict[str, int]:
        counts = await seed_reference_data(session)

        # Relabelled for printing. `seed_reference_data` keeps identifier-ish
        # keys because tests and other callers index into it.
        return {
            "roles": counts["roles"],
            "permissions": counts["permissions"],
            "roles granted": counts["roles_granted"],
            "settings": counts["settings"],
            "translations": counts["translations"],
        }
