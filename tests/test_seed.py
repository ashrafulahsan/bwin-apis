"""Tests for the seeding script."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.roles.models.role import Role
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.repositories.user import UserRepository
from scripts.seed import DEMO_USERS, seed_demo_users, seed_reference_data

PASSWORD = "SeedTest#2026"


@pytest.fixture
async def seeded(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A database seeded exactly as the script leaves it."""

    async def wipe() -> None:
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.commit()

    await wipe()
    await seed_reference_data(session)
    await seed_demo_users(session, PASSWORD)

    yield session

    await wipe()


async def test_every_role_has_at_least_one_user(seeded: AsyncSession) -> None:
    """The point of the demo data: no role is left without an account."""
    roles = await RoleService(seeded).list_all()
    assert len(roles) == 7

    for role in roles:
        holders = await seeded.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == role.id)
        )
        assert holders.first() is not None, f"no user holds '{role.slug}'"


async def test_all_demo_users_are_created(seeded: AsyncSession) -> None:
    total = await seeded.execute(select(User))

    assert len(list(total.scalars().all())) == len(DEMO_USERS)


async def test_seeding_users_twice_creates_nothing(seeded: AsyncSession) -> None:
    """The script is safe to re-run against an existing database."""
    created = await seed_demo_users(seeded, PASSWORD)

    assert created == []


async def test_reference_data_seeding_is_idempotent(seeded: AsyncSession) -> None:
    counts = await seed_reference_data(seeded)

    assert counts["roles"] == 0
    assert counts["permissions"] == 0


async def test_demo_accounts_can_sign_in_with_either_identifier(
    seeded: AsyncSession,
) -> None:
    repository = UserRepository(seeded)

    by_email = await repository.get_by_identifier("student@bwin.example.com")
    by_phone = await repository.get_by_identifier("+8801700000007")

    assert by_email is not None
    assert by_phone is not None
    assert by_email.id == by_phone.id


async def test_demo_accounts_can_sign_in_with_a_local_phone_number(
    seeded: AsyncSession,
) -> None:
    """The format a Bangladeshi user actually types."""
    found = await UserRepository(seeded).get_by_identifier("01700000007")

    assert found is not None
    assert found.email == "student@bwin.example.com"


async def test_super_admin_holds_every_permission(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("superadmin@bwin.example.com")
    permissions = await seeded.execute(select(Permission))

    assert user is not None
    assert len(user.permission_codes) == len(list(permissions.scalars().all()))


async def test_editor_cannot_publish(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("editor@bwin.example.com")

    assert user is not None
    assert user.has_permission("page.update") is True
    assert user.has_permission("page.publish") is False


async def test_the_multi_role_account_combines_permissions(
    seeded: AsyncSession,
) -> None:
    """A single `role_id` column could not express this."""
    user = await UserRepository(seeded).get_by_email("lead.instructor@bwin.example.com")

    assert user is not None
    assert user.role_slugs == {"instructor", "content-manager"}
    assert user.has_permission("course.create") is True
    assert user.has_permission("page.publish") is True


async def test_the_social_account_has_no_password(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("google.user@bwin.example.com")

    assert user is not None
    assert user.has_password is False
    assert user.linked_providers() == {"google"}
    assert user.email_verified is True


async def test_lifecycle_states_are_represented(seeded: AsyncSession) -> None:
    """Pending and suspended accounts exist, so status filters have data."""
    repository = UserRepository(seeded)

    pending = await repository.get_by_email("pending@bwin.example.com")
    suspended = await repository.get_by_email("suspended@bwin.example.com")

    assert pending is not None
    assert pending.status == UserStatus.PENDING
    assert pending.email_verified is False

    assert suspended is not None
    assert suspended.status == UserStatus.SUSPENDED
    assert suspended.can_sign_in is False


def test_demo_emails_use_a_reserved_domain() -> None:
    """`example.com` is reserved by RFC 2606, so it can never be delivered to."""
    for spec in DEMO_USERS:
        assert spec["email"].endswith("@bwin.example.com")


def test_every_system_role_appears_in_the_demo_data() -> None:
    """A new role added without a demo account would fail here."""
    covered = {slug for spec in DEMO_USERS for slug in spec["roles"]}

    assert covered == {
        "super-admin",
        "admin",
        "content-manager",
        "editor",
        "instructor",
        "support",
        "student",
    }
