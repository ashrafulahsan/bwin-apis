"""Seed the database with reference data and demo accounts.

    python -m scripts.seed

Reference data - roles, permissions and their default grants - is also applied
by migration, so this only fills gaps. Translations and demo users are not, so
this is how they get in.

Demo accounts share one known password, which is exactly why this is a script
and not a migration: a migration would create them on every deployment,
including production, leaving well-known credentials on a live system. Seeding
refuses to run against production unless explicitly forced.

Every run is idempotent - accounts that already exist are left alone.
"""

import argparse
import asyncio
import sys
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import Language
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.settings.services.setting import SettingService
from app.modules.translations.services.translation import TranslationService
from app.modules.users.constants import AuthProvider, UserStatus
from app.modules.users.schemas.user import SocialLogin, UserCreate
from app.modules.users.services.user import UserService

DEFAULT_PASSWORD = "BwinDemo#2026"


class DemoUser(TypedDict, total=False):
    email: str
    phone: str
    first_name: str
    last_name: str
    roles: list[str]
    status: UserStatus
    language: Language
    verified: bool
    with_password: bool
    social: tuple[AuthProvider, str]


#: One account per role, plus a few that exercise states the single-role
#: accounts do not: several roles at once, social-only sign-in, and the
#: pending and suspended lifecycle states.
DEMO_USERS: list[DemoUser] = [
    {
        "email": "superadmin@bwin.example.com",
        "phone": "+8801700000001",
        "first_name": "Nusrat",
        "last_name": "Jahan",
        "roles": ["super-admin"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "admin@bwin.example.com",
        "phone": "+8801700000002",
        "first_name": "Rafiqul",
        "last_name": "Islam",
        "roles": ["admin"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "content@bwin.example.com",
        "phone": "+8801700000003",
        "first_name": "Sadia",
        "last_name": "Rahman",
        "roles": ["content-manager"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "language": Language.BN,
    },
    {
        "email": "editor@bwin.example.com",
        "phone": "+8801700000004",
        "first_name": "Tanvir",
        "last_name": "Hasan",
        "roles": ["editor"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "instructor@bwin.example.com",
        "phone": "+8801700000005",
        "first_name": "Mahmuda",
        "last_name": "Akter",
        "roles": ["instructor"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "support@bwin.example.com",
        "phone": "+8801700000006",
        "first_name": "Imran",
        "last_name": "Kabir",
        "roles": ["support"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "language": Language.BN,
    },
    {
        "email": "student@bwin.example.com",
        "phone": "+8801700000007",
        "first_name": "Arif",
        "last_name": "Chowdhury",
        "roles": ["student"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    # Two roles at once - the case a single `role_id` column could not model.
    {
        "email": "lead.instructor@bwin.example.com",
        "phone": "+8801700000008",
        "first_name": "Farhana",
        "last_name": "Siddique",
        "roles": ["instructor", "content-manager"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    # Signed up through Google, so no password and no phone.
    {
        "email": "google.user@bwin.example.com",
        "first_name": "Shahriar",
        "last_name": "Alam",
        "roles": ["student"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "with_password": False,
        "social": (AuthProvider.GOOGLE, "google-demo-1001"),
    },
    # Registered but not yet verified.
    {
        "email": "pending@bwin.example.com",
        "phone": "+8801700000010",
        "first_name": "Rumana",
        "last_name": "Parvin",
        "roles": ["student"],
        "status": UserStatus.PENDING,
        "verified": False,
    },
    # Blocked by an administrator.
    {
        "email": "suspended@bwin.example.com",
        "phone": "+8801700000011",
        "first_name": "Jamal",
        "last_name": "Uddin",
        "roles": ["student"],
        "status": UserStatus.SUSPENDED,
        "verified": True,
    },
]


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


async def seed_demo_users(session: AsyncSession, password: str) -> list[str]:
    """Create any demo account that is missing. Returns the emails created."""
    users = UserService(session)
    roles = RoleRepository(session)
    created: list[str] = []

    for spec in DEMO_USERS:
        email = spec["email"]

        if await users.repository.get_by_email(email) is not None:
            continue

        role_ids = []
        for slug in spec["roles"]:
            role = await roles.get_by_slug(slug)
            if role is None:
                raise SystemExit(
                    f"Role '{slug}' is missing. Run `alembic upgrade head` first."
                )
            role_ids.append(role.id)

        user = await users.create(
            UserCreate(
                email=email,
                phone=spec.get("phone"),
                first_name=spec["first_name"],
                last_name=spec.get("last_name"),
                password=password if spec.get("with_password", True) else None,
                status=spec.get("status", UserStatus.ACTIVE),
                language=spec.get("language", Language.EN),
                role_ids=role_ids,
            )
        )

        if spec.get("verified"):
            # Only flips PENDING to ACTIVE, so a suspended account stays put.
            await users.verify_email(user.id)
            if user.phone:
                await users.verify_phone(user.id)

        if social := spec.get("social"):
            provider, provider_user_id = social
            await users.link_social_account(
                user.id,
                SocialLogin(
                    provider=provider,
                    provider_user_id=provider_user_id,
                    email=email,
                ),
            )

        created.append(email)

    return created


async def report(session: AsyncSession) -> None:
    """Print one line per role, showing it has at least one account."""
    users = UserService(session)

    print("\n  ROLE              USERS  EXAMPLE")
    print("  " + "-" * 58)

    for role in await RoleService(session).list_all():
        holders, total = await users.list_users(_AllPages(), role_slug=role.slug)
        example = holders[0].email if holders else "-- none --"
        print(f"  {role.slug:<18}{total:>4}   {example}")


class _AllPages:
    """Pagination stand-in for a report that wants everything."""

    page = 1
    page_size = 100


async def main(password: str, *, force: bool, skip_users: bool) -> None:
    if settings.is_production and not force:
        raise SystemExit(
            "Refusing to seed against production.\n"
            "Demo accounts share a known password, which must never exist on a "
            "live system. Pass --force only if you are certain."
        )

    # Imported here so the production guard runs before any connection opens.
    from app.core.database import AsyncSessionFactory, dispose_engine

    print(f"Seeding {settings.postgres_db} ({settings.environment.value})")

    async with AsyncSessionFactory() as session:
        counts = await seed_reference_data(session)
        print(
            f"  reference data: {counts['roles']} roles, "
            f"{counts['permissions']} permissions, "
            f"{counts['roles_granted']} roles granted, "
            f"{counts['settings']} settings, "
            f"{counts['translations']} translations"
        )

        if skip_users:
            print("  demo users: skipped")
        else:
            created = await seed_demo_users(session, password)
            print(
                f"  demo users: {len(created)} created, "
                f"{len(DEMO_USERS) - len(created)} already present"
            )

        await report(session)

    await dispose_engine()

    if not skip_users:
        print(f"\n  Demo password: {password}")
        print("  Sign in with either the email or the phone number.\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Password given to every demo account.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow seeding even when ENVIRONMENT is production.",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Seed reference data only, leaving demo accounts out.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.password, force=args.force, skip_users=args.skip_users))
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise
