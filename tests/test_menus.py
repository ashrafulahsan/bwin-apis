"""Tests for menu items.

Two themes run through these. The first is that a menu's category is an
ordinary category, and nothing in the schema stops the wrong one being
attached - a foreign key names a table, not a subset of it - so the check that
keeps the Menu Category taxonomy apart is tested directly.

The second is the shape of the tree: a parent pointer is easy to store and
easy to corrupt, so the guards against cycles, cross-navigation parents and
runaway depth are pinned here.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
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
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.categories.schemas.category import CategoryCreate, CategoryUpdate
from app.modules.categories.services.category import CategoryService
from app.modules.menus.constants import (
    MAX_MENU_DEPTH,
    MENU_CATEGORY_TYPE_ID,
    MENU_CATEGORY_TYPE_NAME,
    MENU_CATEGORY_TYPE_SLUG,
)
from app.modules.menus.models.menu import Menu
from app.modules.menus.schemas.menu import MenuCreate, MenuRead, MenuUpdate
from app.modules.menus.services.menu import MenuService
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

PASSWORD = "MenuTest#2026"


class Navigation:
    """The seeded taxonomy, plus two navigations inside it."""

    def __init__(
        self, taxonomy: CategoryType, main: Category, footer: Category
    ) -> None:
        self.taxonomy = taxonomy
        self.main = main
        self.footer = footer


@pytest.fixture
async def menus(session: AsyncSession) -> AsyncIterator[MenuService]:
    async def wipe() -> None:
        # Menus before categories: an item points at the category it belongs
        # to, and the foreign key is RESTRICT.
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

    yield MenuService(session)

    await wipe()


@pytest.fixture
async def navigation(menus: MenuService, session: AsyncSession) -> Navigation:
    """The taxonomy as the migration seeds it, with two navigations in it.

    Created through the repository rather than the service, because both the
    id and the slug are fixed identifiers and the service derives slugs from
    names.
    """
    taxonomy = await CategoryTypeRepository(session).create(
        id=MENU_CATEGORY_TYPE_ID,
        name=MENU_CATEGORY_TYPE_NAME,
        slug=MENU_CATEGORY_TYPE_SLUG,
        status=CategoryStatus.ACTIVE.value,
    )
    await session.commit()

    categories = CategoryService(session)
    main = await categories.create(
        CategoryCreate(name="Main Menu", category_type_id=taxonomy.id)
    )
    footer = await categories.create(
        CategoryCreate(name="Footer Menu", category_type_id=taxonomy.id)
    )

    return Navigation(taxonomy, main, footer)


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


def item(navigation: Navigation, title: str = "Home", **kwargs) -> MenuCreate:
    payload = {
        "title": title,
        "menu_category_id": navigation.main.id,
        **kwargs,
    }
    return MenuCreate(**payload)


def page() -> PaginationParams:
    return PaginationParams(page=1, page_size=100)


# -- Creating -----------------------------------------------------------


async def test_an_item_is_created_in_its_navigation(
    menus: MenuService, navigation: Navigation
) -> None:
    created = await menus.create(
        item(navigation, link="/", icon="house", image="/img/home.png")
    )

    assert created.menu_category_id == navigation.main.id
    assert created.link == "/"
    assert created.icon == "house"
    assert created.image == "/img/home.png"
    assert created.is_root is True


async def test_the_response_renders_straight_after_creation(
    menus: MenuService, navigation: Navigation
) -> None:
    """Regression: `selectin` loads on query, not on flush.

    A freshly inserted item has `menu_category` unloaded, so rendering the
    response reached for it and raised MissingGreenlet.
    """
    created = await menus.create(item(navigation))

    rendered = MenuRead.model_validate(created)

    assert rendered.menu_category.name == "Main Menu"


async def test_order_defaults_to_last_among_siblings(
    menus: MenuService, navigation: Navigation
) -> None:
    first = await menus.create(item(navigation, title="Home"))
    second = await menus.create(item(navigation, title="About"))
    child = await menus.create(item(navigation, title="Team", parent_id=second.id))

    assert (first.order, second.order) == (1, 2)
    # Numbering restarts per parent, so a first child is 1 rather than 3.
    assert child.order == 1


async def test_an_explicit_order_is_honoured(
    menus: MenuService, navigation: Navigation
) -> None:
    created = await menus.create(item(navigation, order=7))

    assert created.order == 7


def test_a_non_positive_order_is_rejected_by_the_schema(
    navigation: Navigation,
) -> None:
    with pytest.raises(ValueError):
        MenuCreate(title="Home", menu_category_id=navigation.main.id, order=0)


async def test_an_unknown_menu_category_is_refused(
    menus: MenuService, navigation: Navigation
) -> None:
    with pytest.raises(BadRequestException):
        await menus.create(MenuCreate(title="Orphan", menu_category_id=uuid.uuid4()))


async def test_a_missing_taxonomy_says_so(
    menus: MenuService, navigation: Navigation, session: AsyncSession
) -> None:
    """Seeded by migration, so its absence means someone removed it."""
    await session.execute(delete(Menu))
    await session.execute(delete(Category))
    await session.execute(delete(CategoryType))
    await session.commit()

    with pytest.raises(ConflictException) as refusal:
        await menus.create(MenuCreate(title="Home", menu_category_id=uuid.uuid4()))

    assert MENU_CATEGORY_TYPE_SLUG in refusal.value.message


async def test_a_category_from_another_taxonomy_is_refused(
    menus: MenuService, navigation: Navigation, session: AsyncSession
) -> None:
    """A foreign key names a table, not a subset of it, so the service checks."""
    other = await CategoryTypeRepository(session).create(
        name="Blog Category", slug="blog_category", status=CategoryStatus.ACTIVE.value
    )
    await session.commit()

    topic = await CategoryService(session).create(
        CategoryCreate(name="Engineering", category_type_id=other.id)
    )

    with pytest.raises(BadRequestException) as refusal:
        await menus.create(MenuCreate(title="Nope", menu_category_id=topic.id))

    assert MENU_CATEGORY_TYPE_NAME in refusal.value.message


async def test_an_inactive_menu_category_is_refused(
    menus: MenuService, navigation: Navigation, session: AsyncSession
) -> None:
    await CategoryService(session).update(
        navigation.main.id, CategoryUpdate(status=CategoryStatus.INACTIVE)
    )

    with pytest.raises(BadRequestException) as refusal:
        await menus.create(item(navigation))

    assert "inactive" in refusal.value.message


async def test_the_actor_is_recorded(
    menus: MenuService, navigation: Navigation, session: AsyncSession
) -> None:
    admin = await make_user(session, "admin@menus.example.com", "admin")

    created = await menus.create(item(navigation), actor_id=admin.id)

    assert created.created_by == admin.id
    assert created.updated_by == admin.id


# -- The tree -----------------------------------------------------------


async def test_a_parent_must_be_in_the_same_navigation(
    menus: MenuService, navigation: Navigation
) -> None:
    """Otherwise one navigation grows a branch out of another."""
    footer_item = await menus.create(
        MenuCreate(title="Privacy", menu_category_id=navigation.footer.id)
    )

    with pytest.raises(BadRequestException) as refusal:
        await menus.create(item(navigation, title="Terms", parent_id=footer_item.id))

    assert "same menu category" in refusal.value.message


async def test_an_unknown_parent_is_refused(
    menus: MenuService, navigation: Navigation
) -> None:
    with pytest.raises(BadRequestException):
        await menus.create(item(navigation, parent_id=uuid.uuid4()))


async def test_an_item_cannot_be_its_own_parent(
    menus: MenuService, navigation: Navigation
) -> None:
    created = await menus.create(item(navigation))

    with pytest.raises(BadRequestException):
        await menus.move(created.id, created.id)


async def test_an_item_cannot_move_under_its_own_descendant(
    menus: MenuService, navigation: Navigation
) -> None:
    """It would cut the branch out of the tree and leave it in a ring."""
    top = await menus.create(item(navigation, title="Products"))
    child = await menus.create(item(navigation, title="Software", parent_id=top.id))
    grandchild = await menus.create(item(navigation, title="CMS", parent_id=child.id))

    with pytest.raises(BadRequestException) as refusal:
        await menus.move(top.id, grandchild.id)

    assert "cannot" in refusal.value.message


async def test_nesting_stops_at_the_depth_limit(
    menus: MenuService, navigation: Navigation
) -> None:
    parent_id = None
    for level in range(MAX_MENU_DEPTH):
        created = await menus.create(
            item(navigation, title=f"Level {level + 1}", parent_id=parent_id)
        )
        parent_id = created.id

    with pytest.raises(BadRequestException) as refusal:
        await menus.create(item(navigation, title="Too deep", parent_id=parent_id))

    assert str(MAX_MENU_DEPTH) in refusal.value.message


async def test_moving_to_the_top_level_clears_the_parent(
    menus: MenuService, navigation: Navigation
) -> None:
    top = await menus.create(item(navigation, title="Products"))
    child = await menus.create(item(navigation, title="Software", parent_id=top.id))

    moved = await menus.move(child.id, None)

    assert moved.parent_id is None
    assert moved.is_root is True


async def test_an_update_can_promote_an_item_to_the_top_level(
    menus: MenuService, navigation: Navigation
) -> None:
    """An explicit null re-parents; an omitted field leaves the parent alone."""
    top = await menus.create(item(navigation, title="Products"))
    child = await menus.create(item(navigation, title="Software", parent_id=top.id))

    renamed = await menus.update(child.id, MenuUpdate(title="Platform"))
    assert renamed.parent_id == top.id

    promoted = await menus.update(child.id, MenuUpdate(parent_id=None))
    assert promoted.parent_id is None


async def test_the_tree_is_nested_and_ordered(
    menus: MenuService, navigation: Navigation
) -> None:
    products = await menus.create(item(navigation, title="Products", order=2))
    await menus.create(item(navigation, title="Home", order=1))
    await menus.create(item(navigation, title="CMS", parent_id=products.id, order=2))
    await menus.create(item(navigation, title="LMS", parent_id=products.id, order=1))
    # Another navigation entirely, which must not appear in this tree.
    await menus.create(
        MenuCreate(title="Privacy", menu_category_id=navigation.footer.id)
    )

    tree = await menus.tree(navigation.main.id)

    assert [node.title for node in tree] == ["Home", "Products"]
    assert [child.title for child in tree[1].children] == ["LMS", "CMS"]


async def test_ancestors_read_from_the_nearest_parent_up(
    menus: MenuService, navigation: Navigation
) -> None:
    top = await menus.create(item(navigation, title="Products"))
    child = await menus.create(item(navigation, title="Software", parent_id=top.id))
    leaf = await menus.create(item(navigation, title="CMS", parent_id=child.id))

    trail = await menus.ancestors_of(leaf.id)

    assert [row.title for row in trail] == ["Software", "Products"]


async def test_children_are_listed_in_order(
    menus: MenuService, navigation: Navigation
) -> None:
    top = await menus.create(item(navigation, title="Products"))
    await menus.create(item(navigation, title="CMS", parent_id=top.id, order=2))
    await menus.create(item(navigation, title="LMS", parent_id=top.id, order=1))

    children = await menus.children_of(top.id)

    assert [row.title for row in children] == ["LMS", "CMS"]


async def test_changing_navigation_is_refused_while_the_branch_would_split(
    menus: MenuService, navigation: Navigation
) -> None:
    top = await menus.create(item(navigation, title="Products"))
    child = await menus.create(item(navigation, title="Software", parent_id=top.id))

    with pytest.raises(BadRequestException):
        await menus.update(top.id, MenuUpdate(menu_category_id=navigation.footer.id))

    with pytest.raises(BadRequestException):
        await menus.update(child.id, MenuUpdate(menu_category_id=navigation.footer.id))


async def test_a_lone_item_can_change_navigation(
    menus: MenuService, navigation: Navigation
) -> None:
    created = await menus.create(item(navigation, title="Contact"))

    moved = await menus.update(
        created.id, MenuUpdate(menu_category_id=navigation.footer.id)
    )

    assert moved.menu_category_id == navigation.footer.id


# -- Deleting -----------------------------------------------------------


async def test_deleting_is_refused_while_children_exist(
    menus: MenuService, navigation: Navigation
) -> None:
    """Cascading would remove a whole branch of a live navigation."""
    top = await menus.create(item(navigation, title="Products"))
    await menus.create(item(navigation, title="Software", parent_id=top.id))

    with pytest.raises(ConflictException) as refusal:
        await menus.delete(top.id)

    assert "1 child item" in refusal.value.message


async def test_an_item_can_be_deleted_and_restored(
    menus: MenuService, navigation: Navigation
) -> None:
    created = await menus.create(item(navigation))

    await menus.delete(created.id)

    with pytest.raises(NotFoundException):
        await menus.get(created.id)

    restored = await menus.restore(created.id)
    assert restored.deleted_at is None


# -- Listing ------------------------------------------------------------


async def test_items_can_be_searched_and_filtered(
    menus: MenuService, navigation: Navigation
) -> None:
    top = await menus.create(item(navigation, title="Products", link="/products"))
    await menus.create(item(navigation, title="Software", parent_id=top.id))
    await menus.create(
        MenuCreate(title="Privacy", menu_category_id=navigation.footer.id)
    )

    found, total = await menus.list_menus(page(), search="products")
    assert total == 1
    assert found[0].title == "Products"

    _, in_footer = await menus.list_menus(page(), menu_category_id=navigation.footer.id)
    assert in_footer == 1

    roots, root_count = await menus.list_menus(
        page(), menu_category_id=navigation.main.id, roots_only=True
    )
    assert root_count == 1
    assert roots[0].title == "Products"

    children, child_count = await menus.list_menus(page(), parent_id=top.id)
    assert child_count == 1
    assert children[0].title == "Software"


async def test_a_listing_reads_in_order_by_default(
    menus: MenuService, navigation: Navigation
) -> None:
    """The shared sort default is descending, which reads a menu backwards."""
    await menus.create(item(navigation, title="Contact", order=3))
    await menus.create(item(navigation, title="Home", order=1))
    await menus.create(item(navigation, title="About", order=2))

    listed, _ = await menus.list_menus(page())

    assert [row.title for row in listed] == ["Home", "About", "Contact"]


async def test_naming_a_column_hands_the_direction_back_to_the_caller(
    menus: MenuService, navigation: Navigation
) -> None:
    await menus.create(item(navigation, title="Home", order=1))
    await menus.create(item(navigation, title="About", order=2))

    listed, _ = await menus.list_menus(
        page(), sort_by="order", sort_order=SortOrder.DESC
    )

    assert [row.title for row in listed] == ["About", "Home"]


async def test_the_available_categories_are_the_active_menu_ones(
    menus: MenuService, navigation: Navigation, session: AsyncSession
) -> None:
    await CategoryService(session).update(
        navigation.footer.id, CategoryUpdate(status=CategoryStatus.INACTIVE)
    )

    available = await menus.available_categories()

    assert [row.name for row in available] == ["Main Menu"]


# -- Authorization ------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, menus: MenuService, session: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the guards can be checked from outside."""
    headers = {}

    for role in ("admin", "content-manager", "editor", "student"):
        email = f"{role}@menus.example.com"
        await make_user(session, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_menu_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/menus").status_code == 401


def test_an_editor_reads_but_does_not_rearrange(
    client: TestClient, signed_in: dict[str, dict[str, str]], navigation: Navigation
) -> None:
    editor = signed_in["editor"]

    assert client.get("/api/v1/menus", headers=editor).status_code == 200

    created = client.post(
        "/api/v1/menus",
        headers=editor,
        json={"title": "Nope", "menu_category_id": str(navigation.main.id)},
    )

    assert created.status_code == 403
    assert "menu.create" in created.json()["message"]


def test_a_content_manager_walks_the_whole_lifecycle(
    client: TestClient, signed_in: dict[str, dict[str, str]], navigation: Navigation
) -> None:
    manager = signed_in["content-manager"]

    categories = client.get("/api/v1/menus/categories", headers=manager)
    assert categories.status_code == 200
    assert {row["name"] for row in categories.json()["data"]} == {
        "Main Menu",
        "Footer Menu",
    }

    created = client.post(
        "/api/v1/menus",
        headers=manager,
        json={
            "title": "Products",
            "link": "/products",
            "icon": "grid",
            "menu_category_id": str(navigation.main.id),
        },
    )
    assert created.status_code == 201, created.text
    parent = created.json()["data"]

    child = client.post(
        "/api/v1/menus",
        headers=manager,
        json={
            "title": "Software",
            "menu_category_id": str(navigation.main.id),
            "parent_id": parent["id"],
        },
    )
    assert child.status_code == 201, child.text

    updated = client.patch(
        f"/api/v1/menus/{parent['id']}", headers=manager, json={"title": "Our products"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "Our products"

    tree = client.get(
        f"/api/v1/menus/tree?menu_category_id={navigation.main.id}", headers=manager
    )
    assert tree.status_code == 200
    assert [node["title"] for node in tree.json()["data"]] == ["Our products"]
    assert [node["title"] for node in tree.json()["data"][0]["children"]] == [
        "Software"
    ]

    blocked = client.delete(f"/api/v1/menus/{parent['id']}", headers=manager)
    assert blocked.status_code == 409

    moved = client.put(
        f"/api/v1/menus/{child.json()['data']['id']}/parent",
        headers=manager,
        json={"parent_id": None},
    )
    assert moved.status_code == 200
    assert moved.json()["data"]["parent_id"] is None

    deleted = client.delete(f"/api/v1/menus/{parent['id']}", headers=manager)
    assert deleted.status_code == 200
    assert (
        client.get(f"/api/v1/menus/{parent['id']}", headers=manager).status_code == 404
    )

    restored = client.post(f"/api/v1/menus/{parent['id']}/restore", headers=manager)
    assert restored.status_code == 200


def test_a_student_may_read_but_not_write(
    client: TestClient, signed_in: dict[str, dict[str, str]], navigation: Navigation
) -> None:
    student = signed_in["student"]

    assert client.get("/api/v1/menus", headers=student).status_code == 200

    created = client.post(
        "/api/v1/menus",
        headers=student,
        json={"title": "Nope", "menu_category_id": str(navigation.main.id)},
    )
    assert created.status_code == 403
