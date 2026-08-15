"""Tests for the roles module."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.roles.constants import SYSTEM_ROLES, SystemRole
from app.modules.roles.models.role import Role
from app.modules.roles.schemas.role import RoleCreate, RoleUpdate
from app.modules.roles.services.role import RoleService


@pytest.fixture
async def roles(session: AsyncSession) -> AsyncIterator[RoleService]:
    """A service over an empty roles table, cleaned up afterwards."""
    await session.execute(delete(Role))
    await session.commit()

    yield RoleService(session)

    await session.execute(delete(Role))
    await session.commit()


@pytest.fixture
async def seeded(roles: RoleService) -> RoleService:
    await roles.seed_system_roles()
    return roles


# -- Seeding ------------------------------------------------------------


async def test_seeding_creates_every_system_role(roles: RoleService) -> None:
    created = await roles.seed_system_roles()

    assert created == len(SYSTEM_ROLES) == 7


async def test_seeded_roles_cover_the_expected_slugs(seeded: RoleService) -> None:
    all_roles = await seeded.list_all()

    assert {role.slug for role in all_roles} == {
        "super-admin",
        "admin",
        "content-manager",
        "editor",
        "instructor",
        "support",
        "student",
    }


async def test_seeding_is_idempotent(seeded: RoleService) -> None:
    """Safe to run on every boot."""
    assert await seeded.seed_system_roles() == 0


async def test_seeding_does_not_reset_renamed_roles(seeded: RoleService) -> None:
    """An administrator's rename must survive the next deploy."""
    admin = await seeded.get_by_slug(SystemRole.ADMIN)
    await seeded.update(admin.id, RoleUpdate(name="Platform Admin"))

    await seeded.seed_system_roles()

    assert (await seeded.get_by_slug(SystemRole.ADMIN)).name == "Platform Admin"


async def test_roles_are_ordered_by_privilege(seeded: RoleService) -> None:
    all_roles = await seeded.list_all()

    assert [role.slug for role in all_roles] == [
        "super-admin",
        "admin",
        "content-manager",
        "editor",
        "instructor",
        "support",
        "student",
    ]


async def test_super_admin_outranks_everyone(seeded: RoleService) -> None:
    super_admin = await seeded.get_by_slug(SystemRole.SUPER_ADMIN)

    for role in await seeded.list_all():
        if role.slug != SystemRole.SUPER_ADMIN:
            assert super_admin.outranks(role)


# -- Create -------------------------------------------------------------


async def test_create_derives_the_slug(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Course Reviewer", level=45))

    assert role.slug == "course-reviewer"
    assert role.is_system is False


async def test_create_rejects_a_duplicate_name(roles: RoleService) -> None:
    await roles.create(RoleCreate(name="Reviewer"))

    with pytest.raises(ConflictException, match="already exists"):
        await roles.create(RoleCreate(name="Reviewer"))


async def test_duplicate_name_check_is_case_insensitive(roles: RoleService) -> None:
    await roles.create(RoleCreate(name="Reviewer"))

    with pytest.raises(ConflictException):
        await roles.create(RoleCreate(name="reviewer"))


async def test_slug_collisions_get_a_suffix(roles: RoleService) -> None:
    """Two different names can slugify identically."""
    await roles.create(RoleCreate(name="Course Reviewer"))
    second = await roles.create(RoleCreate(name="Course  reviewer!"))

    assert second.slug == "course-reviewer-2"


async def test_create_normalizes_whitespace_in_names(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="  Content   Manager  "))

    assert role.name == "Content Manager"


@pytest.mark.parametrize("level", [-1, 101])
def test_level_must_stay_within_range(level: int) -> None:
    with pytest.raises(ValueError, match="less than or equal|greater than or equal"):
        RoleCreate(name="Anything", level=level)


def test_blank_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="blank|at least"):
        RoleCreate(name="   ")


# -- Read ---------------------------------------------------------------


async def test_get_by_slug(seeded: RoleService) -> None:
    role = await seeded.get_by_slug(SystemRole.INSTRUCTOR)

    assert role.name == "Instructor"


async def test_get_by_unknown_slug_raises(seeded: RoleService) -> None:
    with pytest.raises(NotFoundException, match="not found"):
        await seeded.get_by_slug("nope")


async def test_get_by_unknown_id_raises(seeded: RoleService) -> None:
    with pytest.raises(NotFoundException):
        await seeded.get(uuid.uuid4())


async def test_list_roles_paginates(seeded: RoleService) -> None:
    items, total = await seeded.list_roles(PaginationParams(page=1, page_size=3))

    assert len(items) == 3
    assert total == 7


async def test_list_roles_filters_to_custom_roles(seeded: RoleService) -> None:
    await seeded.create(RoleCreate(name="Reviewer"))

    items, total = await seeded.list_roles(PaginationParams(), is_system=False)

    assert total == 1
    assert items[0].slug == "reviewer"


async def test_list_roles_searches_name_and_description(
    seeded: RoleService,
) -> None:
    items, _ = await seeded.list_roles(PaginationParams(), search="courses")

    assert "instructor" in {item.slug for item in items}


# -- Update -------------------------------------------------------------


async def test_update_changes_the_name(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))

    updated = await roles.update(role.id, RoleUpdate(name="Senior Reviewer"))

    assert updated.name == "Senior Reviewer"


async def test_renaming_never_changes_the_slug(roles: RoleService) -> None:
    """Code refers to roles by slug, so it must survive a rename."""
    role = await roles.create(RoleCreate(name="Reviewer"))

    updated = await roles.update(role.id, RoleUpdate(name="Senior Reviewer"))

    assert updated.slug == "reviewer"


async def test_update_rejects_a_name_taken_by_another_role(
    roles: RoleService,
) -> None:
    await roles.create(RoleCreate(name="Reviewer"))
    second = await roles.create(RoleCreate(name="Auditor"))

    with pytest.raises(ConflictException):
        await roles.update(second.id, RoleUpdate(name="Reviewer"))


async def test_update_allows_setting_a_role_its_own_name(
    roles: RoleService,
) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))

    updated = await roles.update(role.id, RoleUpdate(name="Reviewer"))

    assert updated.name == "Reviewer"


async def test_an_empty_update_is_a_no_op(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))

    updated = await roles.update(role.id, RoleUpdate())

    assert updated.name == "Reviewer"


async def test_system_roles_can_be_renamed(seeded: RoleService) -> None:
    admin = await seeded.get_by_slug(SystemRole.ADMIN)

    updated = await seeded.update(admin.id, RoleUpdate(name="Administrator"))

    assert updated.name == "Administrator"
    assert updated.slug == "admin"


async def test_system_role_level_is_immutable(seeded: RoleService) -> None:
    """Authorization compares levels, so demoting Super Admin must be refused."""
    super_admin = await seeded.get_by_slug(SystemRole.SUPER_ADMIN)

    with pytest.raises(ForbiddenException, match="level of the system role"):
        await seeded.update(super_admin.id, RoleUpdate(level=5))


async def test_custom_role_level_can_change(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Reviewer", level=20))

    updated = await roles.update(role.id, RoleUpdate(level=45))

    assert updated.level == 45


# -- Delete -------------------------------------------------------------


async def test_delete_soft_deletes_a_custom_role(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))

    await roles.delete(role.id)

    _, total = await roles.list_roles(PaginationParams())
    assert total == 0


async def test_system_roles_cannot_be_deleted(seeded: RoleService) -> None:
    """Deleting Super Admin would lock every administrator out."""
    super_admin = await seeded.get_by_slug(SystemRole.SUPER_ADMIN)

    with pytest.raises(ForbiddenException, match="system role"):
        await seeded.delete(super_admin.id)


async def test_every_seeded_role_is_protected(seeded: RoleService) -> None:
    for role in await seeded.list_all():
        with pytest.raises(ForbiddenException):
            await seeded.delete(role.id)


async def test_restore_brings_a_role_back(roles: RoleService) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))
    await roles.delete(role.id)

    restored = await roles.restore(role.id)

    assert restored.deleted_at is None
    _, total = await roles.list_roles(PaginationParams())
    assert total == 1


async def test_a_deleted_role_still_holds_its_name(roles: RoleService) -> None:
    """Name uniqueness is a database constraint that ignores soft delete.

    Reusing the name is refused, with a message that explains why - the
    conflicting role is invisible in every listing.
    """
    role = await roles.create(RoleCreate(name="Reviewer"))
    await roles.delete(role.id)

    with pytest.raises(ConflictException, match="deleted role named"):
        await roles.create(RoleCreate(name="Reviewer"))


async def test_restoring_is_the_way_back_to_a_deleted_name(
    roles: RoleService,
) -> None:
    role = await roles.create(RoleCreate(name="Reviewer"))
    await roles.delete(role.id)

    await roles.restore(role.id)

    assert (await roles.get_by_slug("reviewer")).name == "Reviewer"


async def test_a_deleted_role_still_holds_its_slug(roles: RoleService) -> None:
    """A differently named role slugifying the same gets a suffix."""
    role = await roles.create(RoleCreate(name="Reviewer"))
    await roles.delete(role.id)

    recreated = await roles.create(RoleCreate(name="reviewer!"))

    assert recreated.slug == "reviewer-2"
