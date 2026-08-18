"""Menu endpoints.

Reading requires `menu.view`; each write requires its own code - see
[permissions.py](../permissions.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.categories.schemas.category import CategorySummary
from app.modules.menus.permissions import (
    can_create,
    can_delete,
    can_update,
    can_view,
)
from app.modules.menus.schemas.menu import (
    MenuCreate,
    MenuMove,
    MenuNode,
    MenuRead,
    MenuSummary,
    MenuUpdate,
)
from app.modules.menus.services.menu import MenuService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/menus", tags=["Menus"], dependencies=[can_view()])

MenuId = Annotated[uuid.UUID, Path(description="Menu item identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[MenuRead]],
    summary="List menu items",
    description=(
        "Search matches the title, description and link. `parent_id` returns "
        "one item's children; `roots_only` returns the top level. Results "
        "read in `order`, ascending, unless `sort_by` names another column - "
        "which puts the caller in charge of `sort_order` too."
    ),
)
async def list_menus(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    menu_category_id: Annotated[
        uuid.UUID | None, Query(description="Filter by menu category.")
    ] = None,
    parent_id: Annotated[
        uuid.UUID | None, Query(description="Return this item's children.")
    ] = None,
    roots_only: Annotated[
        bool, Query(description="Return only top-level items.")
    ] = False,
) -> APIResponse[Page[MenuRead]]:
    items, total = await MenuService(db).list_menus(
        pagination,
        search=search.search,
        menu_category_id=menu_category_id,
        parent_id=parent_id,
        roots_only=roots_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [MenuRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Menu items fetched",
    )


@router.get(
    "/tree",
    response_model=APIResponse[list[MenuNode]],
    summary="Get a whole navigation, nested",
    description=(
        "Every item in one menu category, nested and in order, in a single "
        "query - what rendering a navigation needs. An item whose parent is "
        "missing is promoted to the top rather than dropped, so nothing "
        "vanishes without being deleted."
    ),
)
async def get_menu_tree(
    db: DbSession,
    menu_category_id: Annotated[uuid.UUID, Query(description="Which navigation.")],
) -> APIResponse[list[MenuNode]]:
    tree = await MenuService(db).tree(menu_category_id)

    return success_response(data=tree, message="Menu tree fetched")


@router.get(
    "/categories",
    response_model=APIResponse[list[CategorySummary]],
    summary="List the menu categories an item may belong to",
    description=(
        "The active categories from the Menu Category taxonomy. Exposed here "
        "because building a navigation needs this list, while the category "
        "management endpoints are restricted to administrators."
    ),
)
async def list_menu_categories(db: DbSession) -> APIResponse[list[CategorySummary]]:
    categories = await MenuService(db).available_categories()

    return success_response(
        data=[CategorySummary.model_validate(item) for item in categories],
        message="Menu categories fetched",
    )


@router.get(
    "/{menu_id}",
    response_model=APIResponse[MenuRead],
    summary="Get a menu item",
)
async def get_menu(db: DbSession, menu_id: MenuId) -> APIResponse[MenuRead]:
    menu = await MenuService(db).get(menu_id)

    return success_response(
        data=MenuRead.model_validate(menu), message="Menu item fetched"
    )


@router.get(
    "/{menu_id}/children",
    response_model=APIResponse[list[MenuSummary]],
    summary="List a menu item's direct children",
)
async def list_children(
    db: DbSession, menu_id: MenuId
) -> APIResponse[list[MenuSummary]]:
    children = await MenuService(db).children_of(menu_id)

    return success_response(
        data=[MenuSummary.model_validate(item) for item in children],
        message="Child menu items fetched",
    )


@router.get(
    "/{menu_id}/ancestors",
    response_model=APIResponse[list[MenuSummary]],
    summary="List a menu item's ancestors",
    description="Nearest parent first, up to the top. What breadcrumbs need.",
)
async def list_ancestors(
    db: DbSession, menu_id: MenuId
) -> APIResponse[list[MenuSummary]]:
    ancestors = await MenuService(db).ancestors_of(menu_id)

    return success_response(
        data=[MenuSummary.model_validate(item) for item in ancestors],
        message="Ancestors fetched",
    )


@router.post(
    "",
    response_model=APIResponse[MenuRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a menu item",
    description=(
        "Omit `parent_id` for a top-level item. A parent must belong to the "
        "same menu category. Omitting `order` puts the item last among its "
        "siblings."
    ),
    dependencies=[can_create()],
)
async def create_menu(
    db: DbSession, user: CurrentUser, payload: MenuCreate
) -> APIResponse[MenuRead]:
    menu = await MenuService(db).create(payload, actor_id=user.id)

    return created_response(
        data=MenuRead.model_validate(menu), message="Menu item created"
    )


@router.patch(
    "/{menu_id}",
    response_model=APIResponse[MenuRead],
    summary="Update a menu item",
    description=(
        "Sending `parent_id: null` moves the item to the top level; omitting "
        "the field leaves the parent alone."
    ),
    dependencies=[can_update()],
)
async def update_menu(
    db: DbSession, user: CurrentUser, menu_id: MenuId, payload: MenuUpdate
) -> APIResponse[MenuRead]:
    menu = await MenuService(db).update(menu_id, payload, actor_id=user.id)

    return success_response(
        data=MenuRead.model_validate(menu), message="Menu item updated"
    )


@router.put(
    "/{menu_id}/parent",
    response_model=APIResponse[MenuRead],
    summary="Move a menu item",
    description=(
        "Re-parents an item, and places it among its new siblings. Refused "
        "when the new parent sits under the item being moved, which would cut "
        "the branch out of the tree."
    ),
    dependencies=[can_update()],
)
async def move_menu(
    db: DbSession, user: CurrentUser, menu_id: MenuId, payload: MenuMove
) -> APIResponse[MenuRead]:
    menu = await MenuService(db).move(
        menu_id, payload.parent_id, order=payload.order, actor_id=user.id
    )

    return success_response(
        data=MenuRead.model_validate(menu), message="Menu item moved"
    )


@router.delete(
    "/{menu_id}",
    response_model=APIResponse[None],
    summary="Delete a menu item",
    description=(
        "Soft delete, refused while the item still has children - cascading "
        "would remove a whole branch of the navigation on one click."
    ),
    dependencies=[can_delete()],
)
async def delete_menu(db: DbSession, menu_id: MenuId) -> APIResponse[None]:
    await MenuService(db).delete(menu_id)

    return deleted_response("Menu item deleted")


@router.post(
    "/{menu_id}/restore",
    response_model=APIResponse[MenuRead],
    summary="Restore a deleted menu item",
    dependencies=[can_delete()],
)
async def restore_menu(db: DbSession, menu_id: MenuId) -> APIResponse[MenuRead]:
    menu = await MenuService(db).restore(menu_id)

    return success_response(
        data=MenuRead.model_validate(menu), message="Menu item restored"
    )
