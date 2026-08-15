"""Tests for the permissions module and role-permission mapping."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.permissions.constants import (
    DEFAULT_ROLE_PERMISSIONS,
    all_permission_codes,
    build_code,
    build_label,
    split_code,
)
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.schemas.permission import (
    PermissionCodes,
    PermissionCreate,
    PermissionUpdate,
)
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.services.role import RoleService


@pytest.fixture
async def permissions(session: AsyncSession) -> AsyncIterator[PermissionService]:
    """Empty permission and role tables, restored afterwards."""
    await session.execute(delete(role_permissions))
    await session.execute(delete(Permission))
    await session.execute(delete(Role))
    await session.commit()

    yield PermissionService(session)

    await session.execute(delete(role_permissions))
    await session.execute(delete(Permission))
    await session.execute(delete(Role))
    await session.commit()


@pytest.fixture
async def seeded(
    permissions: PermissionService, session: AsyncSession
) -> PermissionService:
    """Roles, permissions and the default grant matrix."""
    await RoleService(session).seed_system_roles()
    await permissions.seed_system_permissions()
    await permissions.seed_default_role_permissions()
    return permissions


# -- Code format --------------------------------------------------------


@pytest.mark.parametrize(
    ("resource", "action", "code"),
    [
        ("user", "view", "user.view"),
        ("user", "create", "user.create"),
        ("course", "view", "course.view"),
        ("course", "create", "course.create"),
    ],
)
def test_code_format(resource: str, action: str, code: str) -> None:
    assert build_code(resource, action) == code
    assert split_code(code) == (resource, action)


def test_labels_read_naturally() -> None:
    assert build_label("user", "view") == "View users"
    assert build_label("course", "create") == "Create courses"


@pytest.mark.parametrize(
    "code", ["user.view", "course.create", "media.upload", "translation.import"]
)
def test_schema_accepts_valid_codes(code: str) -> None:
    assert PermissionCreate(code=code).code == code


@pytest.mark.parametrize(
    "code",
    ["nodot", "user..view", "user.view.extra", ".view", "user.", "9a.b", "a b.c"],
)
def test_schema_rejects_malformed_codes(code: str) -> None:
    with pytest.raises(ValueError, match="resource.action|at most"):
        PermissionCreate(code=code)


def test_schema_normalizes_case_and_whitespace() -> None:
    assert PermissionCreate(code="  USER.VIEW  ").code == "user.view"


def test_code_list_deduplicates_while_keeping_order() -> None:
    payload = PermissionCodes(codes=["user.view", "user.create", "user.view"])

    assert payload.codes == ["user.view", "user.create"]


# -- Seeding ------------------------------------------------------------


async def test_seeding_creates_every_permission(
    permissions: PermissionService,
) -> None:
    created = await permissions.seed_system_permissions()

    assert created == len(all_permission_codes()) == 55


async def test_seeding_is_idempotent(seeded: PermissionService) -> None:
    assert await seeded.seed_system_permissions() == 0


async def test_super_admin_receives_every_permission(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("super-admin")

    granted = await seeded.permissions_for_role(role.id)

    assert len(granted) == len(all_permission_codes())


async def test_editor_can_write_but_not_publish(
    seeded: PermissionService, session: AsyncSession
) -> None:
    """The whole point of the Editor role."""
    role = await RoleService(session).get_by_slug("editor")

    assert await seeded.role_has_permission(role.id, "page.update") is True
    assert await seeded.role_has_permission(role.id, "page.publish") is False
    assert await seeded.role_has_permission(role.id, "page.delete") is False


async def test_content_manager_can_publish(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("content-manager")

    assert await seeded.role_has_permission(role.id, "page.publish") is True


async def test_student_holds_only_read_access(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("student")

    granted = await seeded.permissions_for_role(role.id)

    assert all(permission.action == "view" for permission in granted)


async def test_instructor_can_grade_but_not_manage_users(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("instructor")

    assert await seeded.role_has_permission(role.id, "enrollment.grade") is True
    assert await seeded.role_has_permission(role.id, "user.delete") is False


async def test_default_grants_do_not_overwrite_customization(
    seeded: PermissionService, session: AsyncSession
) -> None:
    """A deploy must not undo an administrator's changes."""
    role = await RoleService(session).get_by_slug("student")
    await seeded.replace(role.id, ["course.view"])

    await seeded.seed_default_role_permissions()

    granted = await seeded.permissions_for_role(role.id)
    assert [permission.code for permission in granted] == ["course.view"]


def test_every_default_grant_names_a_real_permission() -> None:
    """A typo in the matrix would silently grant nothing."""
    known = set(all_permission_codes())

    for slug, codes in DEFAULT_ROLE_PERMISSIONS.items():
        if codes == "*":
            continue
        unknown = set(codes) - known
        assert not unknown, f"{slug} references unknown codes: {unknown}"


# -- Role relationship --------------------------------------------------


async def test_role_exposes_its_permissions(
    seeded: PermissionService, session: AsyncSession
) -> None:
    """The relationship is eager, so this does not raise MissingGreenlet."""
    role = await RoleService(session).get_by_slug("editor")

    assert "page.update" in role.permission_codes
    assert role.has_permission("page.update") is True
    assert role.has_permission("page.publish") is False


# -- Grant, revoke, replace ---------------------------------------------


async def test_grant_adds_permissions(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("student")

    granted = await seeded.grant(role.id, ["media.view"])

    assert "media.view" in {permission.code for permission in granted}


async def test_granting_twice_is_not_an_error(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("student")
    await seeded.grant(role.id, ["media.view"])

    granted = await seeded.grant(role.id, ["media.view"])

    assert [p.code for p in granted].count("media.view") == 1


async def test_revoke_removes_permissions(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("student")

    granted = await seeded.revoke(role.id, ["course.view"])

    assert "course.view" not in {permission.code for permission in granted}


async def test_revoking_something_not_held_is_harmless(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("student")
    before = len(await seeded.permissions_for_role(role.id))

    await seeded.revoke(role.id, ["media.delete"])

    assert len(await seeded.permissions_for_role(role.id)) == before


async def test_replace_sets_the_exact_permission_set(
    seeded: PermissionService, session: AsyncSession
) -> None:
    role = await RoleService(session).get_by_slug("support")

    granted = await seeded.replace(role.id, ["user.view", "report.export"])

    assert [permission.code for permission in granted] == [
        "report.export",
        "user.view",
    ]


async def test_unknown_codes_are_rejected_rather_than_skipped(
    seeded: PermissionService, session: AsyncSession
) -> None:
    """Skipping silently would leave an admin thinking access was granted."""
    role = await RoleService(session).get_by_slug("student")

    with pytest.raises(BadRequestException, match="Unknown permission code"):
        await seeded.grant(role.id, ["course.view", "nonsense.action"])


async def test_grants_against_an_unknown_role_raise(
    seeded: PermissionService,
) -> None:
    with pytest.raises(NotFoundException):
        await seeded.grant(uuid.uuid4(), ["course.view"])


# -- CRUD ---------------------------------------------------------------


async def test_create_derives_resource_action_and_label(
    permissions: PermissionService,
) -> None:
    permission = await permissions.create(PermissionCreate(code="invoice.approve"))

    assert permission.resource == "invoice"
    assert permission.action == "approve"
    assert permission.name == "Approve invoice"
    assert permission.is_system is False


async def test_create_accepts_an_explicit_name(
    permissions: PermissionService,
) -> None:
    permission = await permissions.create(
        PermissionCreate(code="invoice.approve", name="Approve invoices")
    )

    assert permission.name == "Approve invoices"


async def test_create_rejects_a_duplicate_code(
    permissions: PermissionService,
) -> None:
    await permissions.create(PermissionCreate(code="invoice.approve"))

    with pytest.raises(ConflictException, match="already exists"):
        await permissions.create(PermissionCreate(code="invoice.approve"))


async def test_update_changes_the_label(permissions: PermissionService) -> None:
    permission = await permissions.create(PermissionCreate(code="invoice.approve"))

    updated = await permissions.update(
        permission.id, PermissionUpdate(name="Sign off invoices")
    )

    assert updated.name == "Sign off invoices"
    assert updated.code == "invoice.approve"


async def test_delete_removes_an_unused_permission(
    permissions: PermissionService,
) -> None:
    permission = await permissions.create(PermissionCreate(code="invoice.approve"))

    await permissions.delete(permission.id)

    _, total = await permissions.list_permissions(PaginationParams())
    assert total == 0


async def test_system_permissions_cannot_be_deleted(
    seeded: PermissionService,
) -> None:
    permission = await seeded.repository.get_by_code("user.view")
    assert permission is not None

    with pytest.raises(ForbiddenException, match="system permission"):
        await seeded.delete(permission.id)


async def test_a_granted_permission_cannot_be_deleted(
    permissions: PermissionService, session: AsyncSession
) -> None:
    """Deleting it would silently strip access from every role holding it."""
    await RoleService(session).seed_system_roles()
    permission = await permissions.create(PermissionCreate(code="invoice.approve"))
    role = await RoleService(session).get_by_slug("admin")
    await permissions.grant(role.id, ["invoice.approve"])

    with pytest.raises(ConflictException, match="still granted to 1 role"):
        await permissions.delete(permission.id)


# -- Listing ------------------------------------------------------------


async def test_list_filters_by_resource(seeded: PermissionService) -> None:
    items, total = await seeded.list_permissions(PaginationParams(), resource="course")

    assert total == 5
    assert all(item.resource == "course" for item in items)


async def test_list_filters_by_action(seeded: PermissionService) -> None:
    _, total = await seeded.list_permissions(PaginationParams(), action="publish")

    # Courses, pages and blogs are the three things that get published.
    assert total == 3


async def test_grouped_by_resource(seeded: PermissionService) -> None:
    grouped = await seeded.grouped_by_resource()

    assert set(grouped) == {
        "user",
        "role",
        "permission",
        "course",
        "lesson",
        "enrollment",
        "page",
        "blog",
        "media",
        "category",
        "translation",
        "setting",
        "report",
        "notification",
    }
    assert [p.code for p in grouped["course"]] == [
        "course.create",
        "course.delete",
        "course.publish",
        "course.update",
        "course.view",
    ]


async def test_list_resources(seeded: PermissionService) -> None:
    resources = await seeded.list_resources()

    assert "course" in resources
    assert resources == sorted(resources)
