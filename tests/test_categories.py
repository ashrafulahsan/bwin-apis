"""Tests for category types and categories.

Most of these defend the shape of the tree. A parent pointer is easy to store
and easy to corrupt - nothing in the column stops a category becoming its own
grandparent, or being filed under a branch of another taxonomy.
"""

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
from app.modules.categories.constants import (
    MAX_CATEGORY_DEPTH,
    CategoryStatus,
)
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.schemas.category import (
    CategoryCreate,
    CategoryTypeCreate,
    CategoryTypeUpdate,
    CategoryUpdate,
)
from app.modules.categories.services.category import CategoryService
from app.modules.categories.services.category_type import CategoryTypeService
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

PASSWORD = "CategoryTest#2026"


@pytest.fixture
async def types(session: AsyncSession) -> AsyncIterator[CategoryTypeService]:
    async def wipe() -> None:
        # Menus point at categories with a RESTRICT foreign key, so an
        # item left behind by another module blocks this wipe.
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

    yield CategoryTypeService(session)

    await wipe()


@pytest.fixture
def categories(types: CategoryTypeService, session: AsyncSession) -> CategoryService:
    return CategoryService(session)


@pytest.fixture
async def blog(types: CategoryTypeService) -> CategoryType:
    return await types.create(CategoryTypeCreate(name="Blog Topics"))


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


def page() -> PaginationParams:
    return PaginationParams(page=1, page_size=100)


# -- Category types -----------------------------------------------------


async def test_a_type_gets_a_slug_from_its_name(types: CategoryTypeService) -> None:
    created = await types.create(CategoryTypeCreate(name="Course Subjects"))

    assert created.slug == "course-subjects"
    assert created.status == CategoryStatus.ACTIVE


async def test_duplicate_type_names_are_refused(types: CategoryTypeService) -> None:
    await types.create(CategoryTypeCreate(name="Blog Topics"))

    with pytest.raises(ConflictException):
        await types.create(CategoryTypeCreate(name="Blog Topics"))


async def test_type_slugs_are_made_unique(types: CategoryTypeService) -> None:
    """Different names can slugify to the same thing."""
    first = await types.create(CategoryTypeCreate(name="Support Topics"))
    second = await types.create(CategoryTypeCreate(name="Support  Topics!"))

    assert first.slug == "support-topics"
    assert second.slug != first.slug


async def test_the_slug_survives_a_rename(types: CategoryTypeService) -> None:
    """It is already in URLs and in whatever linked to them."""
    created = await types.create(CategoryTypeCreate(name="Blog Topics"))

    renamed = await types.update(created.id, CategoryTypeUpdate(name="Article Topics"))

    assert renamed.name == "Article Topics"
    assert renamed.slug == "blog-topics"


async def test_the_actor_is_recorded(
    types: CategoryTypeService, session: AsyncSession
) -> None:
    admin = await make_user(session, "admin1@bwin.example.com", "admin")

    created = await types.create(
        CategoryTypeCreate(name="Blog Topics"), actor_id=admin.id
    )

    assert created.created_by == admin.id
    assert created.updated_by == admin.id


async def test_updating_records_who_did_it(
    types: CategoryTypeService, session: AsyncSession
) -> None:
    author = await make_user(session, "author@bwin.example.com", "admin")
    editor = await make_user(session, "editor1@bwin.example.com", "admin")

    created = await types.create(
        CategoryTypeCreate(name="Blog Topics"), actor_id=author.id
    )
    updated = await types.update(
        created.id, CategoryTypeUpdate(description="Changed"), actor_id=editor.id
    )

    assert updated.created_by == author.id
    assert updated.updated_by == editor.id


async def test_a_type_holding_categories_cannot_be_deleted(
    types: CategoryTypeService, categories: CategoryService, blog: CategoryType
) -> None:
    """Deleting it anyway would orphan the whole tree."""
    await categories.create(CategoryCreate(name="Design", category_type_id=blog.id))

    with pytest.raises(ConflictException) as refusal:
        await types.delete(blog.id)

    assert "1 category" in refusal.value.message


async def test_an_empty_type_can_be_deleted_and_restored(
    types: CategoryTypeService, blog: CategoryType
) -> None:
    await types.delete(blog.id)

    with pytest.raises(NotFoundException):
        await types.get(blog.id)

    restored = await types.restore(blog.id)
    assert restored.deleted_at is None


async def test_types_can_be_searched_and_filtered(
    types: CategoryTypeService,
) -> None:
    await types.create(CategoryTypeCreate(name="Blog Topics"))
    await types.create(
        CategoryTypeCreate(name="Retired Topics", status=CategoryStatus.INACTIVE)
    )

    found, total = await types.list_types(page(), search="blog")
    assert total == 1
    assert found[0].name == "Blog Topics"

    inactive, count = await types.list_types(page(), status=CategoryStatus.INACTIVE)
    assert count == 1
    assert inactive[0].name == "Retired Topics"


# -- Categories ---------------------------------------------------------


async def test_a_category_is_created_under_its_type(
    categories: CategoryService, blog: CategoryType
) -> None:
    created = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )

    assert created.slug == "design"
    assert created.category_type_id == blog.id
    assert created.is_root is True
    # Reachable straight after the insert: `selectin` loads on query, not on
    # flush, so without a refresh this raises MissingGreenlet when rendered.
    assert created.category_type.name == "Blog Topics"


async def test_an_unknown_type_is_refused(categories: CategoryService) -> None:
    import uuid

    with pytest.raises(BadRequestException):
        await categories.create(
            CategoryCreate(name="Orphan", category_type_id=uuid.uuid4())
        )


async def test_the_same_name_is_refused_within_one_taxonomy(
    categories: CategoryService, blog: CategoryType
) -> None:
    await categories.create(CategoryCreate(name="Design", category_type_id=blog.id))

    with pytest.raises(ConflictException):
        await categories.create(CategoryCreate(name="Design", category_type_id=blog.id))


async def test_the_same_name_is_fine_in_another_taxonomy(
    types: CategoryTypeService, categories: CategoryService, blog: CategoryType
) -> None:
    """ "Design" is reasonably both a blog topic and a course subject."""
    courses = await types.create(CategoryTypeCreate(name="Course Subjects"))

    first = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    second = await categories.create(
        CategoryCreate(name="Design", category_type_id=courses.id)
    )

    assert first.id != second.id
    # The slug is unique platform-wide, so a URL needs no type to resolve.
    assert first.slug != second.slug


async def test_a_child_is_nested_under_its_parent(
    categories: CategoryService, blog: CategoryType
) -> None:
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )

    child = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    assert child.is_root is False
    assert [row.id for row in await categories.children_of(parent.id)] == [child.id]


async def test_a_parent_from_another_taxonomy_is_refused(
    types: CategoryTypeService, categories: CategoryService, blog: CategoryType
) -> None:
    """Otherwise a tree read returns categories that do not belong to it."""
    courses = await types.create(CategoryTypeCreate(name="Course Subjects"))
    outsider = await categories.create(
        CategoryCreate(name="Mathematics", category_type_id=courses.id)
    )

    with pytest.raises(BadRequestException) as refusal:
        await categories.create(
            CategoryCreate(
                name="Algebra",
                category_type_id=blog.id,
                parent_category_id=outsider.id,
            )
        )

    assert "same category type" in refusal.value.message


async def test_ancestors_read_from_the_nearest_parent_up(
    categories: CategoryService, blog: CategoryType
) -> None:
    """What breadcrumbs need."""
    root = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    middle = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=root.id
        )
    )
    leaf = await categories.create(
        CategoryCreate(
            name="Kerning", category_type_id=blog.id, parent_category_id=middle.id
        )
    )

    trail = await categories.ancestors_of(leaf.id)

    assert [row.name for row in trail] == ["Typography", "Design"]


# -- Tree integrity -----------------------------------------------------


async def test_a_category_cannot_be_its_own_parent(
    categories: CategoryService, blog: CategoryType
) -> None:
    category = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )

    with pytest.raises(BadRequestException) as refusal:
        await categories.move(category.id, category.id)

    assert "its own parent" in refusal.value.message


async def test_a_category_cannot_move_under_its_own_child(
    categories: CategoryService, blog: CategoryType
) -> None:
    """That would cut the branch out of the tree, pointing round in a ring."""
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    child = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    with pytest.raises(BadRequestException) as refusal:
        await categories.move(parent.id, child.id)

    assert "cannot" in refusal.value.message


async def test_a_category_cannot_move_under_a_deeper_descendant(
    categories: CategoryService, blog: CategoryType
) -> None:
    """The cycle check has to look past the immediate children."""
    root = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    middle = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=root.id
        )
    )
    leaf = await categories.create(
        CategoryCreate(
            name="Kerning", category_type_id=blog.id, parent_category_id=middle.id
        )
    )

    with pytest.raises(BadRequestException):
        await categories.move(root.id, leaf.id)


async def test_a_category_can_be_promoted_to_the_top(
    categories: CategoryService, blog: CategoryType
) -> None:
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    child = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    promoted = await categories.move(child.id, None)

    assert promoted.is_root is True


async def test_nesting_stops_at_the_depth_limit(
    categories: CategoryService, blog: CategoryType
) -> None:
    parent = await categories.create(
        CategoryCreate(name="Level 1", category_type_id=blog.id)
    )

    for level in range(2, MAX_CATEGORY_DEPTH + 1):
        parent = await categories.create(
            CategoryCreate(
                name=f"Level {level}",
                category_type_id=blog.id,
                parent_category_id=parent.id,
            )
        )

    with pytest.raises(BadRequestException) as refusal:
        await categories.create(
            CategoryCreate(
                name="One too deep",
                category_type_id=blog.id,
                parent_category_id=parent.id,
            )
        )

    assert str(MAX_CATEGORY_DEPTH) in refusal.value.message


async def test_omitting_the_parent_leaves_it_alone(
    categories: CategoryService, blog: CategoryType
) -> None:
    """`exclude_unset` is what separates "not sent" from "set to null"."""
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    child = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    updated = await categories.update(child.id, CategoryUpdate(name="Type"))

    assert updated.parent_category_id == parent.id


async def test_sending_a_null_parent_promotes_the_category(
    categories: CategoryService, blog: CategoryType
) -> None:
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    child = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    updated = await categories.update(child.id, CategoryUpdate(parent_category_id=None))

    assert updated.parent_category_id is None


async def test_a_category_with_children_cannot_change_taxonomy(
    types: CategoryTypeService, categories: CategoryService, blog: CategoryType
) -> None:
    """Its subcategories would be left behind in the old one."""
    courses = await types.create(CategoryTypeCreate(name="Course Subjects"))
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    with pytest.raises(BadRequestException):
        await categories.update(parent.id, CategoryUpdate(category_type_id=courses.id))


async def test_a_lone_category_can_change_taxonomy(
    types: CategoryTypeService, categories: CategoryService, blog: CategoryType
) -> None:
    courses = await types.create(CategoryTypeCreate(name="Course Subjects"))
    category = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )

    moved = await categories.update(
        category.id, CategoryUpdate(category_type_id=courses.id)
    )

    assert moved.category_type_id == courses.id


async def test_a_category_with_children_cannot_be_deleted(
    categories: CategoryService, blog: CategoryType
) -> None:
    """Cascading would remove a whole branch on one click."""
    parent = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=parent.id
        )
    )

    with pytest.raises(ConflictException) as refusal:
        await categories.delete(parent.id)

    assert "1 subcategory" in refusal.value.message


async def test_a_leaf_can_be_deleted_and_restored(
    categories: CategoryService, blog: CategoryType
) -> None:
    category = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )

    await categories.delete(category.id)
    with pytest.raises(NotFoundException):
        await categories.get(category.id)

    assert (await categories.restore(category.id)).deleted_at is None


# -- The tree endpoint --------------------------------------------------


async def test_the_tree_nests_every_level(
    categories: CategoryService, blog: CategoryType
) -> None:
    design = await categories.create(
        CategoryCreate(name="Design", category_type_id=blog.id)
    )
    await categories.create(
        CategoryCreate(name="Engineering", category_type_id=blog.id)
    )
    typography = await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=design.id
        )
    )
    await categories.create(
        CategoryCreate(
            name="Kerning", category_type_id=blog.id, parent_category_id=typography.id
        )
    )

    tree = await categories.tree(blog.id)

    assert [node.name for node in tree] == ["Design", "Engineering"]
    assert [node.name for node in tree[0].children] == ["Typography"]
    assert [node.name for node in tree[0].children[0].children] == ["Kerning"]


async def test_a_filtered_out_parent_promotes_its_children(
    categories: CategoryService, blog: CategoryType
) -> None:
    """Nothing should vanish from a menu without being deleted."""
    design = await categories.create(
        CategoryCreate(
            name="Design", category_type_id=blog.id, status=CategoryStatus.INACTIVE
        )
    )
    await categories.create(
        CategoryCreate(
            name="Typography", category_type_id=blog.id, parent_category_id=design.id
        )
    )

    tree = await categories.tree(blog.id, active_only=True)

    assert [node.name for node in tree] == ["Typography"]


async def test_the_tree_of_an_unknown_taxonomy_is_a_404(
    categories: CategoryService,
) -> None:
    import uuid

    with pytest.raises(NotFoundException):
        await categories.tree(uuid.uuid4())


# -- Authorization ------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, types: CategoryTypeService, session: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the guard can be checked from outside."""
    headers = {}

    for role in ("super-admin", "admin", "content-manager", "editor", "student"):
        email = f"{role}@categories.example.com"
        await make_user(session, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_category_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/category-types").status_code == 401
    assert client.get("/api/v1/categories").status_code == 401


def test_super_admin_and_admin_may_manage_taxonomies(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    for role in ("super-admin", "admin"):
        created = client.post(
            "/api/v1/category-types",
            headers=signed_in[role],
            json={"name": f"Taxonomy by {role}"},
        )
        assert created.status_code == 201, role

        listed = client.get("/api/v1/category-types", headers=signed_in[role])
        assert listed.status_code == 200, role


@pytest.mark.parametrize("role", ["content-manager", "editor", "student"])
def test_every_other_role_is_refused(
    client: TestClient, signed_in: dict[str, dict[str, str]], role: str
) -> None:
    """Including content managers, who hold `category.create` as a permission.

    The guard is by role on purpose - reshaping a taxonomy moves every piece
    of content filed under it.
    """
    listed = client.get("/api/v1/category-types", headers=signed_in[role])
    created = client.post(
        "/api/v1/categories",
        headers=signed_in[role],
        json={
            "name": "Nope",
            "category_type_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert listed.status_code == 403
    assert created.status_code == 403
    assert listed.json()["success"] is False


def test_the_refusal_names_the_roles_allowed(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    response = client.get("/api/v1/category-types", headers=signed_in["editor"])

    assert "admin" in response.json()["message"]


# -- Through the API ----------------------------------------------------


def test_the_full_lifecycle_through_the_api(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    admin = signed_in["admin"]

    taxonomy = client.post(
        "/api/v1/category-types",
        headers=admin,
        json={"name": "API Topics", "description": "Made through the API."},
    ).json()["data"]

    parent = client.post(
        "/api/v1/categories",
        headers=admin,
        json={"name": "Backend", "category_type_id": taxonomy["id"]},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["data"]["id"]
    assert parent.json()["data"]["category_type"]["slug"] == taxonomy["slug"]

    child = client.post(
        "/api/v1/categories",
        headers=admin,
        json={
            "name": "Databases",
            "category_type_id": taxonomy["id"],
            "parent_category_id": parent_id,
        },
    )
    assert child.status_code == 201

    tree = client.get(
        f"/api/v1/categories/tree?category_type_id={taxonomy['id']}", headers=admin
    ).json()["data"]
    assert [node["name"] for node in tree] == ["Backend"]
    assert [node["name"] for node in tree[0]["children"]] == ["Databases"]

    # The parent still has a child, so deleting it is refused.
    blocked = client.delete(f"/api/v1/categories/{parent_id}", headers=admin)
    assert blocked.status_code == 409

    moved = client.put(
        f"/api/v1/categories/{child.json()['data']['id']}/parent",
        headers=admin,
        json={"parent_category_id": None},
    )
    assert moved.status_code == 200
    assert moved.json()["data"]["parent_category_id"] is None

    assert (
        client.delete(f"/api/v1/categories/{parent_id}", headers=admin).status_code
        == 200
    )


def test_the_audit_columns_come_back(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    admin = signed_in["admin"]
    me = client.get("/api/v1/auth/me", headers=admin).json()["data"]

    created = client.post(
        "/api/v1/category-types", headers=admin, json={"name": "Audited"}
    ).json()["data"]

    assert created["created_by"] == me["id"]
    assert created["updated_by"] == me["id"]
    assert created["created_at"] is not None


def test_deleting_and_restoring_render_through_the_api(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    """Regression: both used to fail rendering the row they had just written.

    A soft delete is an UPDATE, which expires `updated_at` - it carries a
    server-side `onupdate` - and reading it back to build the response
    triggered lazy IO. Only the service layer was covered, and it never looks
    at that column, so the endpoints returned 422 while the tests passed.
    """
    admin = signed_in["admin"]

    taxonomy = client.post(
        "/api/v1/category-types", headers=admin, json={"name": "Restorable"}
    ).json()["data"]

    deleted = client.delete(f"/api/v1/category-types/{taxonomy['id']}", headers=admin)
    restored = client.post(
        f"/api/v1/category-types/{taxonomy['id']}/restore", headers=admin
    )

    assert deleted.status_code == 200, deleted.text
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["id"] == taxonomy["id"]
