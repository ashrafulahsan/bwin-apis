"""Tests for the platform-wide activity log.

Three kinds of test live here. The first two are ordinary: the helpers that
shape an entry, and the entries the real services actually write. The third is
the policy suite at the bottom, which reads the source of every module and
fails when one of them grows a write path that does not log - that is what
makes "every future module implements Activity Log" a rule the build enforces
rather than a line in a document.
"""

import ast
import pathlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import (
    EMPTY_CONTEXT,
    RequestContext,
    context_from_scope,
    get_request_context,
    reset_request_context,
    set_request_context,
)
from app.modules.activity_logs.models.activity_log import (
    MANDATORY_ACTIONS,
    ActivityAction,
    ActivityLog,
    ActivityModule,
    ActivityStatus,
)
from app.modules.activity_logs.services.activity_log import ActivityLogQueryService
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.auth.schemas.auth import LoginRequest
from app.modules.auth.services.auth import AuthService
from app.modules.blogs.models.blog import Blog
from app.modules.blogs.models.blog_tag import blog_tags
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.master_cruds.models.master_crud import MasterCrud
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.models.master_crud_field_value import (
    MasterCrudFieldValue,
)
from app.modules.menus.models.menu import Menu
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.schemas.role import RoleCreate, RoleUpdate
from app.modules.roles.services.role import RoleService
from app.modules.settings.services.setting import SettingService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import UserCreate
from app.modules.users.services.user import UserService
from app.shared.services.activity_log_service import (
    REDACTED,
    ActivityLogService,
    diff,
    is_sensitive,
    jsonable,
    snapshot,
)

PASSWORD = "ActivityTest#2026"


# -- Shaping an entry ---------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "password",
        "password_hash",
        "new_password",
        "current_password",
        "token_hash",
        "refresh_token",
        "client_secret",
        "api_key",
        "OTP",
    ],
)
def test_secret_field_names_are_recognised(field: str) -> None:
    assert is_sensitive(field) is True


@pytest.mark.parametrize("field", ["email", "status", "title", "description"])
def test_ordinary_field_names_are_not(field: str) -> None:
    assert is_sensitive(field) is False


def test_a_snapshot_redacts_rather_than_omits() -> None:
    """Omitting it would read as "there was no password"."""
    taken = snapshot({"email": "a@b.com", "password_hash": "$argon2id$v=19$..."})

    assert taken == {"email": "a@b.com", "password_hash": REDACTED}


def test_a_snapshot_drops_surrogate_keys_and_timestamps() -> None:
    taken = snapshot(
        {"id": uuid.uuid4(), "created_at": "x", "updated_at": "y", "name": "Kept"}
    )

    assert taken == {"name": "Kept"}


def test_a_snapshot_makes_values_json_safe() -> None:
    identifier = uuid.uuid4()
    moment = datetime(2026, 8, 17, 10, 30)

    taken = snapshot({"ref": identifier, "at": moment, "status": UserStatus.ACTIVE})

    assert taken == {
        "ref": str(identifier),
        "at": moment.isoformat(),
        "status": "active",
    }


def test_unknown_types_degrade_to_text_rather_than_failing() -> None:
    """A log write must never be the thing that breaks a request."""

    class Odd:
        def __str__(self) -> str:
            return "odd"

    assert jsonable(Odd()) == "odd"


def test_a_diff_keeps_only_what_changed() -> None:
    """An edit to one field should not record forty unchanged ones."""
    old_values, new_values = diff(
        {"name": "Before", "level": 5}, {"name": "After", "level": 5}
    )

    assert old_values == {"name": "Before"}
    assert new_values == {"name": "After"}


def test_a_diff_treats_an_added_field_as_a_change() -> None:
    old_values, new_values = diff({}, {"description": "New"})

    assert old_values == {}
    assert new_values == {"description": "New"}


# -- The request context ------------------------------------------------


def test_the_context_is_empty_outside_a_request() -> None:
    """A seeder or a job logs what it knows and nothing more."""
    assert get_request_context() == EMPTY_CONTEXT


def test_the_context_is_built_from_the_asgi_scope() -> None:
    context = context_from_scope(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/roles",
            "query_string": b"page=2",
            "scheme": "https",
            "client": ("10.0.0.7", 51234),
            "headers": [(b"host", b"api.example.com"), (b"user-agent", b"pytest")],
        }
    )

    assert context.ip_address == "10.0.0.7"
    assert context.user_agent == "pytest"
    assert context.request_method == "POST"
    assert context.request_url == "https://api.example.com/api/v1/roles?page=2"


def test_a_proxied_address_wins_over_the_socket() -> None:
    """Behind a proxy the socket address is the proxy, not the caller."""
    context = context_from_scope(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "client": ("172.16.0.1", 5000),
            "headers": [(b"x-forwarded-for", b"203.0.113.9, 172.16.0.1")],
        }
    )

    assert context.ip_address == "203.0.113.9"


# -- Writing entries ----------------------------------------------------


@pytest.fixture
async def audited(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A database with the reference data in and the log emptied."""

    async def wipe() -> None:
        await session.execute(delete(ActivityLog))
        # Menus and blogs both point at categories with a RESTRICT foreign
        # key, so a row left behind by another module blocks this wipe.
        # Master CRUD values, records and fields all point at categories or
        # at each other with RESTRICT foreign keys, so a row left behind by
        # another module blocks this wipe.
        await session.execute(delete(MasterCrudFieldValue))
        await session.execute(delete(MasterCrud))
        await session.execute(delete(MasterCrudField))
        await session.execute(delete(Menu))
        await session.execute(delete(blog_tags))
        await session.execute(delete(Blog))
        await session.execute(delete(Category))
        await session.execute(delete(CategoryType))
        await session.execute(delete(PasswordResetToken))
        await session.execute(delete(RefreshToken))
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.commit()

    await wipe()
    await RoleService(session).seed_system_roles()
    await PermissionService(session).seed_system_permissions()
    await PermissionService(session).seed_default_role_permissions()
    await session.execute(delete(ActivityLog))
    await session.commit()

    yield session

    await wipe()


async def entries(session: AsyncSession, **filters: object) -> list[ActivityLog]:
    """Every entry recorded so far, oldest first, optionally filtered."""
    conditions = [getattr(ActivityLog, key) == value for key, value in filters.items()]
    result = await session.execute(
        select(ActivityLog).where(*conditions).order_by(ActivityLog.created_at)
    )
    return list(result.scalars().all())


async def make_user(session: AsyncSession, email: str, role: str) -> User:
    role_row = await RoleRepository(session).get_by_slug(role)
    assert role_row is not None

    return await UserService(session).create(
        UserCreate(
            email=email,
            password=PASSWORD,
            first_name=role.title(),
            status=UserStatus.ACTIVE,
            role_ids=[role_row.id],
        )
    )


async def test_creating_a_record_is_logged(audited: AsyncSession) -> None:
    role = await RoleService(audited).create(RoleCreate(name="Auditor", level=40))

    logged = await entries(audited, action=ActivityAction.CREATE.value)

    assert len(logged) == 1
    assert logged[0].module == ActivityModule.ROLES
    assert logged[0].entity_type == "Role"
    assert logged[0].entity_id == str(role.id)
    assert logged[0].new_values["name"] == "Auditor"
    assert logged[0].status == ActivityStatus.SUCCESS


async def test_an_update_records_both_sides_of_the_change(
    audited: AsyncSession,
) -> None:
    roles = RoleService(audited)
    role = await roles.create(RoleCreate(name="Before", level=40))

    await roles.update(role.id, RoleUpdate(name="After"))

    logged = await entries(audited, action=ActivityAction.UPDATE.value)

    assert len(logged) == 1
    assert logged[0].old_values == {"name": "Before"}
    assert logged[0].new_values == {"name": "After"}


async def test_an_update_that_changes_nothing_records_nothing(
    audited: AsyncSession,
) -> None:
    """Saving a form without touching it is not an event."""
    roles = RoleService(audited)
    role = await roles.create(RoleCreate(name="Unchanged", level=40))

    await roles.update(role.id, RoleUpdate(name="Unchanged"))

    assert await entries(audited, action=ActivityAction.UPDATE.value) == []


async def test_a_delete_keeps_what_was_deleted(audited: AsyncSession) -> None:
    """The row is gone from the listing; the log is where it survives."""
    roles = RoleService(audited)
    role = await roles.create(RoleCreate(name="Temporary", level=40))

    await roles.delete(role.id)

    logged = await entries(audited, action=ActivityAction.DELETE.value)

    assert len(logged) == 1
    assert logged[0].old_values["name"] == "Temporary"


async def test_a_user_password_never_reaches_the_log(audited: AsyncSession) -> None:
    await make_user(audited, "hashed@activity.example.com", "student")

    logged = await entries(audited, entity_type="User")
    stored = [entry.new_values for entry in logged if entry.new_values]

    assert stored
    for values in stored:
        assert values.get("password_hash") in (None, REDACTED)
        assert PASSWORD not in str(values)


async def test_a_secret_setting_records_the_change_but_not_the_value(
    audited: AsyncSession,
) -> None:
    """Half of these rows are credentials, and the trail is not a copy of them."""
    settings = SettingService(audited)
    await SettingService(audited).seed_system_settings()
    await audited.execute(delete(ActivityLog))
    await audited.commit()

    await settings.set("google_client_secret", "super-secret-value")

    logged = await entries(audited, action=ActivityAction.SETTINGS_CHANGE.value)

    assert len(logged) == 1
    assert logged[0].entity_id == "google_client_secret"
    assert logged[0].new_values == {"value": REDACTED}
    assert "super-secret-value" not in str(logged[0].new_values)


async def test_a_role_change_records_the_whole_set_either_side(
    audited: AsyncSession,
) -> None:
    users = UserService(audited)
    user = await make_user(audited, "promoted@activity.example.com", "student")
    editor = await RoleRepository(audited).get_by_slug("editor")
    assert editor is not None

    await users.assign_roles(user.id, [editor.id])

    logged = await entries(audited, action=ActivityAction.ROLE_ASSIGN.value)

    assert logged[-1].old_values == {"roles": ["student"]}
    assert logged[-1].new_values == {"roles": ["editor", "student"]}


async def test_a_permission_change_is_logged(audited: AsyncSession) -> None:
    permissions = PermissionService(audited)
    role = await RoleService(audited).create(RoleCreate(name="Grantee", level=30))

    await permissions.grant(role.id, ["user.view"])

    logged = await entries(audited, action=ActivityAction.PERMISSION_GRANT.value)

    assert logged[-1].new_values == {"permissions": ["user.view"]}


async def test_signing_in_is_logged_against_the_account(
    audited: AsyncSession,
) -> None:
    """The caller is not known from the token yet, so the service names them."""
    user = await make_user(audited, "signin@activity.example.com", "student")
    await audited.execute(delete(ActivityLog))
    await audited.commit()

    await AuthService(audited).login(
        LoginRequest(identifier="signin@activity.example.com", password=PASSWORD)
    )

    logged = await entries(audited, action=ActivityAction.LOGIN.value)

    assert len(logged) == 1
    assert logged[0].user_id == user.id
    assert logged[0].user_name == user.full_name
    assert logged[0].role_name == "Student"


async def test_a_refused_sign_in_is_logged_as_a_failure(
    audited: AsyncSession,
) -> None:
    """The entry an audit trail exists for, and the one a rollback would eat."""
    await make_user(audited, "wrong@activity.example.com", "student")

    from app.core.exceptions import UnauthorizedException

    with pytest.raises(UnauthorizedException):
        await AuthService(audited).login(
            LoginRequest(identifier="wrong@activity.example.com", password="Nope#2026")
        )

    logged = await entries(audited, action=ActivityAction.LOGIN_FAILED.value)

    assert len(logged) == 1
    assert logged[0].status == ActivityStatus.FAILURE
    assert "Nope#2026" not in logged[0].description


async def test_signing_out_is_logged(audited: AsyncSession) -> None:
    user = await make_user(audited, "out@activity.example.com", "student")

    await AuthService(audited).logout_everywhere(user.id)

    logged = await entries(audited, action=ActivityAction.LOGOUT.value)

    assert len(logged) == 1
    assert logged[0].entity_id == str(user.id)


async def test_an_entry_carries_the_request_metadata(audited: AsyncSession) -> None:
    """Recorded from the service layer, which never sees the request itself."""
    token = set_request_context(
        RequestContext(
            ip_address="198.51.100.4",
            user_agent="pytest-agent",
            request_method="POST",
            request_url="https://api.example.com/api/v1/roles",
        )
    )
    try:
        await RoleService(audited).create(RoleCreate(name="Traced", level=40))
    finally:
        reset_request_context(token)

    logged = await entries(audited, action=ActivityAction.CREATE.value)

    assert logged[0].ip_address == "198.51.100.4"
    assert logged[0].user_agent == "pytest-agent"
    assert logged[0].request_method == "POST"
    assert logged[0].request_url.endswith("/api/v1/roles")


async def test_a_detached_entry_survives_a_rollback(audited: AsyncSession) -> None:
    """What `record_detached` is for: the caller is about to raise."""
    await ActivityLogService.record_detached(
        ActivityAction.LOGIN_FAILED,
        module=ActivityModule.AUTH,
        description="Detached entry",
    )

    await audited.rollback()

    logged = await entries(audited, description="Detached entry")

    assert len(logged) == 1
    assert logged[0].status == ActivityStatus.FAILURE


async def test_an_entry_is_lost_when_its_transaction_rolls_back(
    audited: AsyncSession,
) -> None:
    """The other half of the contract: a log entry never outlives its change."""
    service = ActivityLogService(audited, ActivityModule.SYSTEM)
    await service.record(ActivityAction.CREATE, description="Never committed")

    await audited.rollback()

    assert await entries(audited, description="Never committed") == []


async def test_the_history_of_one_record_reads_back_in_order(
    audited: AsyncSession,
) -> None:
    roles = RoleService(audited)
    role = await roles.create(RoleCreate(name="Tracked", level=40))
    await roles.update(role.id, RoleUpdate(description="Now described"))
    await roles.delete(role.id)

    history = await ActivityLogQueryService(audited).history_of("Role", str(role.id))

    assert [entry.action for entry in history] == [
        ActivityAction.DELETE,
        ActivityAction.UPDATE,
        ActivityAction.CREATE,
    ]


async def test_entries_can_be_filtered_by_module_and_status(
    audited: AsyncSession,
) -> None:
    await RoleService(audited).create(RoleCreate(name="Filtered", level=40))

    class Page:
        page = 1
        page_size = 50

    items, total = await ActivityLogQueryService(audited).list_entries(
        Page(), module=ActivityModule.ROLES, status=ActivityStatus.SUCCESS
    )

    assert total == len(items) == 1
    assert items[0].module == ActivityModule.ROLES


# -- Through the API ----------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, audited: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the endpoint guard can be checked."""
    headers = {}

    for role in ("admin", "student"):
        email = f"{role}@activity-api.example.com"
        await make_user(audited, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_the_activity_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/activity-logs").status_code == 401


def test_a_student_may_not_read_the_activity_log(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    """Reading everyone's actions is an administrative function."""
    response = client.get("/api/v1/activity-logs", headers=signed_in["student"])

    assert response.status_code == 403


def test_an_admin_reads_the_trail_of_their_own_request(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    """End to end: a write through the API, then the entry it left."""
    created = client.post(
        "/api/v1/category-types",
        headers=signed_in["admin"],
        json={"name": "Made Over HTTP"},
    )
    assert created.status_code == 201

    listed = client.get(
        "/api/v1/activity-logs?module=categories&action=create",
        headers=signed_in["admin"],
    ).json()["data"]["items"]

    assert listed, "the write left no entry"
    entry = listed[0]
    assert entry["description"] == "Created category type Made Over HTTP"
    assert entry["user_name"] == "Admin"
    assert entry["role_name"] == "Admin"
    assert entry["status"] == "success"

    detail = client.get(
        f"/api/v1/activity-logs/{entry['id']}", headers=signed_in["admin"]
    ).json()["data"]

    # Captured by the middleware, from a service that never saw the request.
    assert detail["request_method"] == "POST"
    assert detail["request_url"].endswith("/api/v1/category-types")
    assert detail["ip_address"]
    assert detail["user_agent"]


def test_the_activity_log_is_read_only_over_http(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    """An entry a caller could write by hand would make the trail deniable."""
    admin = signed_in["admin"]

    assert client.post("/api/v1/activity-logs", headers=admin, json={}).status_code in (
        404,
        405,
    )
    assert client.delete(
        f"/api/v1/activity-logs/{uuid.uuid4()}", headers=admin
    ).status_code in (404, 405)


# -- The development rule -----------------------------------------------
#
# A feature is not complete until its business logic, its tests and its
# activity logging are all in place. The tests below are what stops the third
# from being the one that slips: they read every module's source, so a new
# service written next year is held to the same rule without anyone
# remembering to come back here.

SERVICES = sorted(pathlib.Path("app/modules").glob("*/services/*.py"))

#: Methods that commit without logging, each with the reason it is allowed to.
#: Every entry here is a deliberate decision, not a backlog.
LOGGING_EXEMPTIONS = {
    # Issues a replacement token pair during a password change. The caller
    # logs the password change itself; a second entry would double-count one
    # action.
    "AuthService.issue_session",
}


#: What a call to the writer looks like, plus the `_record_*` helpers a
#: service may wrap it in when several methods log the same shape of entry.
RECORDING_CALLS = {"record", "record_failure", "record_detached"}


def called_names(node: ast.AST) -> set[str]:
    """Every attribute and bare name called anywhere inside a function."""
    names = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.Name):
            names.add(child.id)

    return names


def writes_to_the_database(node: ast.AST) -> bool:
    return "commit" in called_names(node)


def records_activity(node: ast.AST) -> bool:
    called = called_names(node)

    return bool(called & RECORDING_CALLS) or any(
        name.startswith("_record") for name in called
    )


def test_there_are_service_modules_to_check() -> None:
    """Guards the rest of the policy suite against silently checking nothing."""
    assert len(SERVICES) >= 10


@pytest.mark.parametrize("path", SERVICES, ids=lambda path: path.stem)
def test_every_service_that_writes_also_logs(path: pathlib.Path) -> None:
    """Rule 3: no create, update or delete may bypass the activity log."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for cls in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        for fn in [
            node
            for node in cls.body
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        ]:
            if fn.name.startswith("_"):
                # Private helpers are logged by the public method that calls
                # them, which is where the action has a name.
                continue
            if not writes_to_the_database(fn):
                continue
            if f"{cls.name}.{fn.name}" in LOGGING_EXEMPTIONS:
                continue

            assert records_activity(fn), (
                f"{path.as_posix()}::{cls.name}.{fn.name} commits without "
                "recording activity. Log it through ActivityLogService, or "
                "add it to LOGGING_EXEMPTIONS with the reason."
            )


def imported_names(path: pathlib.Path) -> set[str]:
    """Every name a module imports.

    Read from the import statements rather than by searching the text, so a
    docstring that mentions `ActivityLogService` is not mistaken for a call
    to it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    return {
        alias.asname or alias.name.rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }


def test_no_router_imports_the_writer() -> None:
    """Rule 4: logging happens in the service layer, never in a router.

    A router knows the request but not what the operation meant, and logging
    there would leave every other caller of the same service unlogged.
    """
    for path in pathlib.Path("app/modules").glob("*/routers/*.py"):
        assert "ActivityLogService" not in imported_names(path), (
            f"{path.as_posix()} writes to the activity log from a router. "
            "Move it into the service that performs the action."
        )


def test_the_centralized_service_is_the_only_writer() -> None:
    """Rule 5: one service writes entries, so the trail has one vocabulary."""
    writers = {
        path.as_posix()
        for path in pathlib.Path("app").rglob("*.py")
        if "ActivityLog(" in path.read_text(encoding="utf-8")
    }

    assert writers == {
        # Where the model is declared, and the one service that instantiates
        # it. Anything else constructing an entry directly would be a second
        # write path, which is the thing this feature exists to prevent.
        "app/modules/activity_logs/models/activity_log.py",
        "app/shared/services/activity_log_service.py",
    }


def test_every_mandatory_action_has_a_name_in_the_vocabulary() -> None:
    """Rule 6: the actions that must be logged are all expressible."""
    assert set(ActivityAction) >= MANDATORY_ACTIONS


def test_the_model_captures_every_required_field() -> None:
    """The field list is a requirement, so it is asserted rather than assumed."""
    required = {
        "user_id",
        "user_name",
        "role_name",
        "action",
        "module",
        "entity_type",
        "entity_id",
        "description",
        "old_values",
        "new_values",
        "ip_address",
        "user_agent",
        "request_method",
        "request_url",
        "status",
        "created_at",
    }

    assert required <= set(ActivityLog.__table__.columns.keys())


def test_the_trail_cannot_be_edited_or_soft_deleted() -> None:
    """Append-only is a property of the schema, not a convention."""
    columns = set(ActivityLog.__table__.columns.keys())

    assert "updated_at" not in columns
    assert "deleted_at" not in columns
