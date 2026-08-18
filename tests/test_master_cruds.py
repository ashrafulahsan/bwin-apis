"""Tests for master CRUD fields, records and their values.

Three themes run through these.

The first is the module's central rule: a record may only answer fields
defined on its own category. Nothing in the schema can express that - a
foreign key names a table, not a subset of it - so the check is tested
directly.

The second is what a stored answer is allowed to be. A dynamic form is only
worth having if "abc" cannot end up in a number field, so the type validation
and its normalization are pinned here.

The third is the deletion rule that was specified: a field records have
answered cannot be deleted.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.schemas.category import (
    CategoryCreate,
    CategoryTypeCreate,
    CategoryUpdate,
)
from app.modules.categories.services.category import CategoryService
from app.modules.categories.services.category_type import CategoryTypeService
from app.modules.master_cruds.constants import FieldType, MasterCrudStatus
from app.modules.master_cruds.models.master_crud import MasterCrud
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.models.master_crud_field_value import MasterCrudFieldValue
from app.modules.master_cruds.schemas.master_crud import (
    MasterCrudCreate,
    MasterCrudFieldValueInput,
    MasterCrudRead,
    MasterCrudUpdate,
)
from app.modules.master_cruds.schemas.master_crud_field import (
    MasterCrudFieldCreate,
    MasterCrudFieldUpdate,
)
from app.modules.master_cruds.services.master_crud import (
    MasterCrudService,
    normalize_field_value,
)
from app.modules.master_cruds.services.master_crud_field import MasterCrudFieldService
from app.modules.menus.models.menu import Menu
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import UserCreate
from app.modules.users.services.user import UserService

PASSWORD = "MasterCrudTest#2026"


class Vocabulary:
    """Two categories to file records under, from one taxonomy."""

    def __init__(self, suppliers: Category, branches: Category) -> None:
        self.suppliers = suppliers
        self.branches = branches


@pytest.fixture
async def fields(session: AsyncSession) -> AsyncIterator[MasterCrudFieldService]:
    async def wipe() -> None:
        # Values first, then records and fields: the value points at both with
        # foreign keys, and the one on the field is RESTRICT.
        await session.execute(delete(MasterCrudFieldValue))
        await session.execute(delete(MasterCrud))
        await session.execute(delete(MasterCrudField))
        await session.execute(delete(Menu))
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

    yield MasterCrudFieldService(session)

    await wipe()


@pytest.fixture
def records(fields: MasterCrudFieldService, session: AsyncSession) -> MasterCrudService:
    return MasterCrudService(session)


@pytest.fixture
async def vocabulary(
    fields: MasterCrudFieldService, session: AsyncSession
) -> Vocabulary:
    taxonomy = await CategoryTypeService(session).create(
        CategoryTypeCreate(name="Directory Types")
    )
    categories = CategoryService(session)

    suppliers = await categories.create(
        CategoryCreate(name="Suppliers", category_type_id=taxonomy.id)
    )
    branches = await categories.create(
        CategoryCreate(name="Branches", category_type_id=taxonomy.id)
    )

    return Vocabulary(suppliers, branches)


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


async def define(
    fields: MasterCrudFieldService,
    vocabulary: Vocabulary,
    name: str = "Phone number",
    **kwargs,
) -> MasterCrudField:
    payload = {
        "category_id": vocabulary.suppliers.id,
        "field_name": name,
        **kwargs,
    }
    return await fields.create(MasterCrudFieldCreate(**payload))


def answer(field: MasterCrudField, value: str | None) -> MasterCrudFieldValueInput:
    return MasterCrudFieldValueInput(master_crud_field_id=field.id, value=value)


def record_for(
    vocabulary: Vocabulary, title: str = "Acme Supplies", **kwargs
) -> MasterCrudCreate:
    payload = {
        "title": title,
        "category_id": vocabulary.suppliers.id,
        **kwargs,
    }
    return MasterCrudCreate(**payload)


def page() -> PaginationParams:
    return PaginationParams(page=1, page_size=100)


# -- Fields -------------------------------------------------------------


async def test_a_field_is_defined_on_a_category(
    fields: MasterCrudFieldService, vocabulary: Vocabulary
) -> None:
    created = await define(
        fields, vocabulary, field_type=FieldType.NUMBER, field_requiredness=True
    )

    assert created.category_id == vocabulary.suppliers.id
    assert created.field_type == FieldType.NUMBER
    assert created.is_required is True
    assert created.is_active is True
    # Reachable straight after the insert: `selectin` loads on query, not on
    # flush, so without the related object this raises MissingGreenlet.
    assert created.category.name == "Suppliers"


async def test_two_fields_in_one_category_cannot_share_a_name(
    fields: MasterCrudFieldService, vocabulary: Vocabulary
) -> None:
    await define(fields, vocabulary)

    with pytest.raises(ConflictException):
        await define(fields, vocabulary)


async def test_the_same_name_is_fine_in_another_category(
    fields: MasterCrudFieldService, vocabulary: Vocabulary
) -> None:
    """ "Phone number" is reasonably asked of both suppliers and branches."""
    first = await define(fields, vocabulary)
    second = await fields.create(
        MasterCrudFieldCreate(
            category_id=vocabulary.branches.id, field_name="Phone number"
        )
    )

    assert first.id != second.id


async def test_an_unknown_category_is_refused(
    fields: MasterCrudFieldService, vocabulary: Vocabulary
) -> None:
    with pytest.raises(BadRequestException):
        await fields.create(
            MasterCrudFieldCreate(category_id=uuid.uuid4(), field_name="Orphan")
        )


async def test_an_inactive_category_takes_no_new_fields(
    fields: MasterCrudFieldService, vocabulary: Vocabulary, session: AsyncSession
) -> None:
    await CategoryService(session).update(
        vocabulary.suppliers.id, CategoryUpdate(status=CategoryStatus.INACTIVE)
    )

    with pytest.raises(BadRequestException):
        await define(fields, vocabulary)


async def test_the_actor_is_recorded(
    fields: MasterCrudFieldService, vocabulary: Vocabulary, session: AsyncSession
) -> None:
    admin = await make_user(session, "admin@mastercruds.example.com", "admin")

    created = await fields.create(
        MasterCrudFieldCreate(
            category_id=vocabulary.suppliers.id, field_name="Contact"
        ),
        actor_id=admin.id,
    )

    assert created.created_by == admin.id
    assert created.updated_by == admin.id


async def test_an_unanswered_field_can_be_deleted_and_restored(
    fields: MasterCrudFieldService, vocabulary: Vocabulary
) -> None:
    created = await define(fields, vocabulary)

    await fields.delete(created.id)

    with pytest.raises(NotFoundException):
        await fields.get(created.id)

    restored = await fields.restore(created.id)
    assert restored.deleted_at is None


# -- The deletion rule --------------------------------------------------


async def test_an_answered_field_cannot_be_deleted(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """The rule the module was asked for, and the reason for RESTRICT."""
    field = await define(fields, vocabulary)
    await records.create(record_for(vocabulary, field_values=[answer(field, "999")]))

    with pytest.raises(ConflictException) as refusal:
        await fields.delete(field.id)

    assert "1 record" in refusal.value.message


async def test_the_refusal_survives_the_record_being_deleted(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """A soft-deleted record still holds its answers, and can be restored."""
    field = await define(fields, vocabulary)
    created = await records.create(
        record_for(vocabulary, field_values=[answer(field, "999")])
    )

    await records.delete(created.id)

    with pytest.raises(ConflictException):
        await fields.delete(field.id)


async def test_an_answered_field_cannot_change_category_or_type(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    field = await define(fields, vocabulary)
    await records.create(record_for(vocabulary, field_values=[answer(field, "999")]))

    with pytest.raises(ConflictException):
        await fields.update(
            field.id, MasterCrudFieldUpdate(category_id=vocabulary.branches.id)
        )

    with pytest.raises(ConflictException):
        await fields.update(field.id, MasterCrudFieldUpdate(field_type=FieldType.DATE))


async def test_an_answered_field_can_still_be_renamed_and_retired(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """Neither changes what a stored answer means, so neither is refused."""
    field = await define(fields, vocabulary)
    await records.create(record_for(vocabulary, field_values=[answer(field, "999")]))

    renamed = await fields.update(
        field.id,
        MasterCrudFieldUpdate(field_name="Telephone", status=MasterCrudStatus.INACTIVE),
    )

    assert renamed.field_name == "Telephone"
    assert renamed.is_active is False


# -- Values -------------------------------------------------------------


async def test_a_record_carries_its_answers(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary)
    since = await define(
        fields, vocabulary, "Supplying since", field_type=FieldType.DATE
    )

    created = await records.create(
        record_for(
            vocabulary,
            field_values=[answer(phone, "01711000000"), answer(since, "2019-04-01")],
        )
    )

    stored = {value.field.field_name: value.value for value in created.field_values}
    assert stored == {"Phone number": "01711000000", "Supplying since": "2019-04-01"}


async def test_the_response_renders_straight_after_creation(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """Regression: `selectin` loads on query, not on flush.

    A value built from a bare field id has its `field` unloaded, so rendering
    the response reached for it and raised MissingGreenlet.
    """
    phone = await define(fields, vocabulary)

    created = await records.create(
        record_for(vocabulary, field_values=[answer(phone, "01711000000")])
    )
    rendered = MasterCrudRead.from_model(created)

    assert rendered.category.name == "Suppliers"
    assert rendered.field_values[0].field_name == "Phone number"


async def test_a_required_field_must_be_answered(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    await define(fields, vocabulary, field_requiredness=True)

    with pytest.raises(BadRequestException) as refusal:
        await records.create(record_for(vocabulary))

    assert "Phone number" in refusal.value.message


async def test_a_blank_answer_does_not_satisfy_a_required_field(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary, field_requiredness=True)

    with pytest.raises(BadRequestException):
        await records.create(
            record_for(vocabulary, field_values=[answer(phone, "   ")])
        )


async def test_a_blank_optional_answer_is_stored_as_nothing(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """ "Not answered" is one value in the database, not two."""
    phone = await define(fields, vocabulary)

    created = await records.create(
        record_for(vocabulary, field_values=[answer(phone, "  ")])
    )

    assert created.field_values[0].value is None


async def test_a_field_from_another_category_is_refused(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """The module's central rule: a foreign key cannot express it."""
    elsewhere = await fields.create(
        MasterCrudFieldCreate(
            category_id=vocabulary.branches.id, field_name="Branch code"
        )
    )

    with pytest.raises(BadRequestException) as refusal:
        await records.create(
            record_for(vocabulary, field_values=[answer(elsewhere, "B-1")])
        )

    assert "own category" in refusal.value.message


async def test_answering_the_same_field_twice_is_refused(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary)

    with pytest.raises(BadRequestException) as refusal:
        await records.create(
            record_for(
                vocabulary, field_values=[answer(phone, "1"), answer(phone, "2")]
            )
        )

    assert "twice" in refusal.value.message


async def test_a_retired_field_is_not_asked_of_new_records(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary, status=MasterCrudStatus.INACTIVE)

    with pytest.raises(BadRequestException) as refusal:
        await records.create(
            record_for(vocabulary, field_values=[answer(phone, "999")])
        )

    assert "inactive" in refusal.value.message


# -- Type validation ----------------------------------------------------


def field_of(field_type: FieldType) -> MasterCrudField:
    """A field object on its own, for testing the pure normalizer."""
    return MasterCrudField(field_name="Answer", field_type=field_type.value)


@pytest.mark.parametrize(
    ("field_type", "raw", "stored"),
    [
        (FieldType.NUMBER, " 42 ", "42"),
        (FieldType.NUMBER, "-3.5", "-3.5"),
        (FieldType.DATE, "2026-08-18", "2026-08-18"),
        (FieldType.DATETIME, "2026-08-18T10:30:00", "2026-08-18T10:30:00"),
        (FieldType.BOOLEAN, "YES", "true"),
        (FieldType.BOOLEAN, "0", "false"),
        (FieldType.EMAIL, "a@b.example.com", "a@b.example.com"),
        (FieldType.URL, "/local/page", "/local/page"),
        (FieldType.TEXT, "  spaced  ", "spaced"),
        (FieldType.RADIO, "second", "second"),
    ],
)
def test_a_value_is_normalized_to_one_spelling(
    field_type: FieldType, raw: str, stored: str
) -> None:
    assert normalize_field_value(field_of(field_type), raw) == stored


@pytest.mark.parametrize(
    ("field_type", "raw"),
    [
        (FieldType.NUMBER, "abc"),
        (FieldType.DATE, "18/08/2026"),
        (FieldType.DATETIME, "yesterday"),
        (FieldType.BOOLEAN, "maybe"),
        (FieldType.EMAIL, "not-an-address"),
        (FieldType.URL, "javascript:alert(1)"),
    ],
)
def test_a_value_that_is_not_its_type_is_refused(
    field_type: FieldType, raw: str
) -> None:
    with pytest.raises(BadRequestException):
        normalize_field_value(field_of(field_type), raw)


def test_a_blank_value_is_nothing_whatever_the_type() -> None:
    assert normalize_field_value(field_of(FieldType.NUMBER), None) is None
    assert normalize_field_value(field_of(FieldType.NUMBER), "   ") is None


async def test_a_bad_value_is_refused_on_the_way_in(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    count = await define(fields, vocabulary, "Headcount", field_type=FieldType.NUMBER)

    with pytest.raises(BadRequestException) as refusal:
        await records.create(
            record_for(vocabulary, field_values=[answer(count, "several")])
        )

    assert "Headcount" in refusal.value.message


# -- Records ------------------------------------------------------------


async def test_a_record_gets_a_slug_and_a_place(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    first = await records.create(record_for(vocabulary, title="Acme Supplies!"))
    second = await records.create(record_for(vocabulary, title="Bolt Traders"))

    assert first.slug == "acme-supplies"
    assert (first.order, second.order) == (1, 2)


async def test_an_explicit_order_is_honoured(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    created = await records.create(record_for(vocabulary, order=9))

    assert created.order == 9


def test_a_non_positive_order_is_rejected_by_the_schema(
    vocabulary: Vocabulary,
) -> None:
    with pytest.raises(ValueError):
        MasterCrudCreate(title="Acme", category_id=vocabulary.suppliers.id, order=0)


async def test_sending_values_replaces_the_whole_set(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """What a form submission means: these are the answers, all of them."""
    phone = await define(fields, vocabulary)
    email = await define(fields, vocabulary, "Email", field_type=FieldType.EMAIL)

    created = await records.create(
        record_for(
            vocabulary,
            field_values=[answer(phone, "999"), answer(email, "a@b.example.com")],
        )
    )

    updated = await records.update(
        created.id, MasterCrudUpdate(field_values=[answer(phone, "111")])
    )

    stored = {value.field.field_name: value.value for value in updated.field_values}
    assert stored == {"Phone number": "111"}


async def test_omitting_values_leaves_the_answers_alone(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary)
    created = await records.create(
        record_for(vocabulary, field_values=[answer(phone, "999")])
    )

    updated = await records.update(created.id, MasterCrudUpdate(title="Acme Ltd"))

    assert updated.title == "Acme Ltd"
    assert [value.value for value in updated.field_values] == ["999"]


async def test_moving_a_record_between_categories_needs_the_new_answers(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    """The old answers belong to the old category's fields."""
    phone = await define(fields, vocabulary)
    code = await fields.create(
        MasterCrudFieldCreate(
            category_id=vocabulary.branches.id, field_name="Branch code"
        )
    )
    created = await records.create(
        record_for(vocabulary, field_values=[answer(phone, "999")])
    )

    with pytest.raises(BadRequestException) as refusal:
        await records.update(
            created.id, MasterCrudUpdate(category_id=vocabulary.branches.id)
        )
    assert "field_values" in refusal.value.message

    moved = await records.update(
        created.id,
        MasterCrudUpdate(
            category_id=vocabulary.branches.id, field_values=[answer(code, "B-1")]
        ),
    )

    assert moved.category_id == vocabulary.branches.id
    stored = {value.field.field_name: value.value for value in moved.field_values}
    assert stored == {"Branch code": "B-1"}


async def test_a_record_can_be_deleted_and_restored_with_its_answers(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    phone = await define(fields, vocabulary)
    created = await records.create(
        record_for(vocabulary, field_values=[answer(phone, "999")])
    )

    await records.delete(created.id)

    with pytest.raises(NotFoundException):
        await records.get(created.id)

    restored = await records.restore(created.id)
    assert [value.value for value in restored.field_values] == ["999"]


async def test_records_read_in_order_and_can_be_filtered(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    await records.create(record_for(vocabulary, title="Bolt Traders", order=2))
    await records.create(record_for(vocabulary, title="Acme Supplies", order=1))
    await records.create(
        MasterCrudCreate(title="Uttara Branch", category_id=vocabulary.branches.id)
    )

    _, total = await records.list_records(page())
    assert total == 3

    # `order` counts from 1 within each category, so a listing is only in a
    # meaningful sequence once it is scoped to one - which is how a client
    # asks for it.
    listed, suppliers = await records.list_records(
        page(), category_id=vocabulary.suppliers.id
    )
    assert suppliers == 2
    assert [row.title for row in listed] == ["Acme Supplies", "Bolt Traders"]

    found, matches = await records.list_records(page(), search="uttara")
    assert matches == 1
    assert found[0].title == "Uttara Branch"


async def test_the_form_lists_only_the_active_fields(
    fields: MasterCrudFieldService, records: MasterCrudService, vocabulary: Vocabulary
) -> None:
    await define(fields, vocabulary)
    await define(fields, vocabulary, "Fax", status=MasterCrudStatus.INACTIVE)

    form = await records.form_for(vocabulary.suppliers.id)

    assert [field.field_name for field in form] == ["Phone number"]


# -- Authorization ------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, fields: MasterCrudFieldService, session: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the guards can be checked from outside."""
    headers = {}

    for role in ("admin", "content-manager", "editor", "student"):
        email = f"{role}@mastercruds.example.com"
        await make_user(session, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_the_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/master-cruds").status_code == 401
    assert client.get("/api/v1/master-crud-fields").status_code == 401


def test_a_content_manager_fills_forms_in_but_does_not_design_them(
    client: TestClient, signed_in: dict[str, dict[str, str]], vocabulary: Vocabulary
) -> None:
    """The reason the two resources have separate permission codes."""
    manager = signed_in["content-manager"]

    assert client.get("/api/v1/master-crud-fields", headers=manager).status_code == 200

    defined = client.post(
        "/api/v1/master-crud-fields",
        headers=manager,
        json={
            "category_id": str(vocabulary.suppliers.id),
            "field_name": "Nope",
        },
    )

    assert defined.status_code == 403
    assert "master_crud_field.create" in defined.json()["message"]


def test_an_editor_writes_records_but_does_not_delete_them(
    client: TestClient, signed_in: dict[str, dict[str, str]], vocabulary: Vocabulary
) -> None:
    editor = signed_in["editor"]

    created = client.post(
        "/api/v1/master-cruds",
        headers=editor,
        json={"title": "Acme Supplies", "category_id": str(vocabulary.suppliers.id)},
    )
    assert created.status_code == 201, created.text

    deleted = client.delete(
        f"/api/v1/master-cruds/{created.json()['data']['id']}", headers=editor
    )
    assert deleted.status_code == 403
    assert "master_crud.delete" in deleted.json()["message"]


def test_an_admin_walks_the_whole_lifecycle(
    client: TestClient, signed_in: dict[str, dict[str, str]], vocabulary: Vocabulary
) -> None:
    admin = signed_in["admin"]
    category_id = str(vocabulary.suppliers.id)

    phone = client.post(
        "/api/v1/master-crud-fields",
        headers=admin,
        json={
            "category_id": category_id,
            "field_name": "Phone number",
            "field_type": "number",
            "field_requiredness": True,
        },
    )
    assert phone.status_code == 201, phone.text
    phone_id = phone.json()["data"]["id"]

    form = client.get(
        f"/api/v1/master-cruds/form?category_id={category_id}", headers=admin
    )
    assert form.status_code == 200
    assert [field["field_name"] for field in form.json()["data"]] == ["Phone number"]

    missing = client.post(
        "/api/v1/master-cruds",
        headers=admin,
        json={"title": "Acme Supplies", "category_id": category_id},
    )
    assert missing.status_code == 400
    assert "Phone number" in missing.json()["message"]

    created = client.post(
        "/api/v1/master-cruds",
        headers=admin,
        json={
            "title": "Acme Supplies",
            "category_id": category_id,
            "link": "/suppliers/acme",
            "field_values": [
                {"master_crud_field_id": phone_id, "value": "01711000000"}
            ],
        },
    )
    assert created.status_code == 201, created.text
    record = created.json()["data"]
    assert record["field_values"][0]["field_name"] == "Phone number"

    blocked = client.delete(f"/api/v1/master-crud-fields/{phone_id}", headers=admin)
    assert blocked.status_code == 409
    assert "1 record" in blocked.json()["message"]

    fetched = client.get(
        f"/api/v1/master-cruds/by-slug/{record['slug']}", headers=admin
    )
    assert fetched.status_code == 200

    updated = client.patch(
        f"/api/v1/master-cruds/{record['id']}",
        headers=admin,
        json={
            "title": "Acme Supplies Ltd",
            "field_values": [
                {"master_crud_field_id": phone_id, "value": "01922000000"}
            ],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["field_values"][0]["value"] == "01922000000"

    deleted = client.delete(f"/api/v1/master-cruds/{record['id']}", headers=admin)
    assert deleted.status_code == 200
    assert (
        client.get(f"/api/v1/master-cruds/{record['id']}", headers=admin).status_code
        == 404
    )

    restored = client.post(
        f"/api/v1/master-cruds/{record['id']}/restore", headers=admin
    )
    assert restored.status_code == 200


def test_a_student_may_read_records_but_not_the_field_definitions(
    client: TestClient, signed_in: dict[str, dict[str, str]], vocabulary: Vocabulary
) -> None:
    student = signed_in["student"]

    assert client.get("/api/v1/master-cruds", headers=student).status_code == 200

    fields_response = client.get("/api/v1/master-crud-fields", headers=student)
    assert fields_response.status_code == 403
    assert "master_crud_field.view" in fields_response.json()["message"]
