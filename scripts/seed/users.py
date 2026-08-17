"""The demo accounts, and the report that shows every role has one.

These share one known password, which is exactly why seeding is a script and
not a migration: a migration would create them on every deployment, including
production, leaving well-known credentials on a live system.

The specs are in `scripts/seed/data/users.py`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Language
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import UserStatus
from app.modules.users.schemas.user import SocialLogin, UserCreate
from app.modules.users.services.user import UserService
from scripts.seed.base import AllPages, Seeder, SeedOptions, heading
from scripts.seed.data.users import DEMO_USERS

DEFAULT_PASSWORD = "BwinDemo#2026"


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


class UserSeeder(Seeder):
    name = "users"
    description = "Demo accounts, one per role, sharing a known password."
    requires = ("reference",)

    async def run(self, session: AsyncSession, options: SeedOptions) -> dict[str, int]:
        created = await seed_demo_users(session, options.password)

        return {
            "created": len(created),
            "already present": len(DEMO_USERS) - len(created),
        }

    async def report(self, session: AsyncSession, options: SeedOptions) -> None:
        """One line per role, showing it has at least one account."""
        users = UserService(session)

        heading("ROLE              USERS  EXAMPLE")

        for role in await RoleService(session).list_all():
            holders, total = await users.list_users(AllPages(), role_slug=role.slug)
            example = holders[0].email if holders else "-- none --"
            print(f"  {role.slug:<18}{total:>4}   {example}")

        print(f"\n  Demo password: {options.password}")
        print("  Sign in with either the email or the phone number.")
