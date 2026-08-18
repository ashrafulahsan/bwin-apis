"""Business logic for menu items.

Two things here are worth reading before the rest.

The first is `_resolve_menu_category`: which navigation an item belongs to is
a row in `categories`, and a foreign key can only say "some category", never
"a category from the Menu Category taxonomy". That restriction is the module's
central rule, so it is checked on every write rather than trusted from the
client.

The second is the shape of the tree. A parent pointer is easy to store and
easy to corrupt: nothing in the column stops an item becoming its own
grandparent, or being filed under a branch of a different navigation. Those
checks live here, because they are rules of the domain rather than of the
table.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
)
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.menus.constants import (
    MAX_MENU_DEPTH,
    MENU_CATEGORY_TYPE_ID,
    MENU_CATEGORY_TYPE_SLUG,
    MENU_SEARCH_FIELDS,
)
from app.modules.menus.models.menu import Menu
from app.modules.menus.repositories.menu import MenuRepository
from app.modules.menus.schemas.menu import MenuCreate, MenuNode, MenuUpdate
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    jsonable,
    snapshot,
)

logger = logging.getLogger(__name__)


class MenuService:
    """Coordinates menu reads, writes and the tree they form.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MenuRepository(session)
        self.categories = CategoryRepository(session)
        self.types = CategoryTypeRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.MENUS)

    # -- Reads ----------------------------------------------------------

    async def get(self, menu_id: uuid.UUID) -> Menu:
        return await self.repository.get_or_raise(menu_id)

    async def list_menus(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        menu_category_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[Menu], int]:
        if sort_by is None:
            # A navigation is read in the order an administrator arranged it,
            # and `order` counts upwards - so the shared `sort_order` default
            # of descending would hand back every menu backwards. Naming a
            # column puts the caller in charge of the direction as well.
            sort_order = SortOrder.ASC

        filters = []

        if menu_category_id is not None:
            filters.append(Filter.eq("menu_category_id", menu_category_id))

        if parent_id is not None:
            filters.append(Filter.eq("parent_id", parent_id))
        elif roots_only:
            filters.append(Filter.is_null("parent_id"))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(MENU_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def children_of(self, menu_id: uuid.UUID) -> list[Menu]:
        menu = await self.repository.get_or_raise(menu_id)
        return await self.repository.children_of(menu.id)

    async def ancestors_of(self, menu_id: uuid.UUID) -> list[Menu]:
        """The trail from the nearest parent up to the top, for breadcrumbs."""
        menu = await self.repository.get_or_raise(menu_id)
        return await self.repository.ancestors_of(menu)

    async def tree(self, menu_category_id: uuid.UUID) -> list[MenuNode]:
        """One navigation's whole tree, in one query.

        Built in memory rather than with a recursive query: the rows are few,
        and one flat SELECT plus a pass to link them beats a round trip per
        level.
        """
        category = await self._resolve_menu_category(menu_category_id, active=False)

        rows = await self.repository.list_for_category(category.id)

        nodes = {
            row.id: MenuNode(
                id=row.id,
                title=row.title,
                description=row.description,
                icon=row.icon,
                image=row.image,
                link=row.link,
                parent_id=row.parent_id,
                order=row.order,
            )
            for row in rows
        }

        roots: list[MenuNode] = []
        for row in rows:
            node = nodes[row.id]
            parent = nodes.get(row.parent_id) if row.parent_id else None
            # An item whose parent is missing - deleted, say - is promoted to
            # the top rather than dropped, so nothing disappears from a
            # navigation without being deleted itself.
            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)

        return roots

    async def available_categories(self) -> list[Category]:
        """The menu categories an item may be filed under.

        Exposed here because building a navigation needs this list, while the
        category management endpoints are restricted to administrators.
        """
        taxonomy = await self._taxonomy()
        return await self.categories.list_for_type(taxonomy.id, active_only=True)

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: MenuCreate, *, actor_id: uuid.UUID | None = None
    ) -> Menu:
        category = await self._resolve_menu_category(payload.menu_category_id)

        if payload.parent_id is not None:
            parent = await self._require_parent(payload.parent_id, category.id)
            await self._guard_depth(parent)

        order = payload.order or await self.repository.next_order(
            category.id, payload.parent_id
        )

        created = await self.repository.create(
            title=payload.title,
            description=payload.description,
            icon=payload.icon,
            image=payload.image,
            link=payload.link,
            parent_id=payload.parent_id,
            # The related object rather than its id: that leaves the
            # relationship loaded in memory, so rendering the response does
            # not reach for an unloaded `menu_category` and raise
            # MissingGreenlet the way a freshly inserted row otherwise would.
            menu_category=category,
            order=order,
            created_by=actor_id,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=created,
            description=f"Created menu item {created.title!r} in {category.name}",
            new_values=snapshot(created),
        )
        await self.session.commit()

        logger.info("Created menu item %s in %s", created.title, category.name)
        return created

    async def update(
        self,
        menu_id: uuid.UUID,
        payload: MenuUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Menu:
        menu = await self.repository.get_or_raise(menu_id)
        changes = payload.model_dump(exclude_unset=True)

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form field it never edited. The
        # alternative is a 500 from the NOT NULL constraint.
        for field in ("title", "menu_category_id", "order"):
            if field in changes and changes[field] is None:
                changes.pop(field)

        if not changes:
            return menu

        category_id = changes.get("menu_category_id", menu.menu_category_id)
        if "menu_category_id" in changes and category_id != menu.menu_category_id:
            await self._resolve_menu_category(category_id)
            await self._guard_category_move(menu)

        if "parent_id" in changes:
            await self._guard_parent(menu, changes["parent_id"], category_id)

        changes["updated_by"] = actor_id

        before = snapshot(menu, fields=changes.keys())
        updated = await self.repository.update(menu, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated menu item {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def move(
        self,
        menu_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        *,
        order: int | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Menu:
        """Re-parent an item, or promote it to the top level with `None`."""
        menu = await self.repository.get_or_raise(menu_id)

        await self._guard_parent(menu, parent_id, menu.menu_category_id)

        previous_parent, previous_order = menu.parent_id, menu.order
        position = order or await self.repository.next_order(
            menu.menu_category_id, parent_id
        )

        updated = await self.repository.update(
            menu, parent_id=parent_id, order=position, updated_by=actor_id
        )

        await self.activity.record(
            ActivityAction.UPDATE,
            entity=updated,
            description=(
                f"Moved menu item {updated.title!r} "
                f"{'under another item' if parent_id else 'to the top level'}"
            ),
            old_values={
                "parent_id": jsonable(previous_parent),
                "order": previous_order,
            },
            new_values={"parent_id": jsonable(parent_id), "order": position},
        )
        await self.session.commit()

        logger.info("Moved menu item %s under %s", menu.title, parent_id)
        return updated

    async def delete(self, menu_id: uuid.UUID) -> None:
        """Soft delete an item, refusing while it still has children.

        Cascading would silently remove a whole branch of a navigation on one
        click. Refusing makes the administrator look at what they are about to
        lose.
        """
        menu = await self.repository.get_or_raise(menu_id)

        children = await self.repository.count_children(menu.id)
        if children:
            raise ConflictException(
                f"'{menu.title}' still has {children} "
                f"{'child item' if children == 1 else 'child items'}. "
                "Delete or move them first."
            )

        before = snapshot(menu)
        await self.repository.soft_delete(menu)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=menu,
            description=f"Deleted menu item {menu.title!r}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted menu item %s", menu.title)

    async def restore(self, menu_id: uuid.UUID) -> Menu:
        menu = await self.repository.get_or_raise(menu_id, include_deleted=True)
        restored = await self.repository.restore(menu)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored menu item {restored.title!r}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    # -- Invariants -----------------------------------------------------

    async def _taxonomy(self) -> CategoryType:
        """The seeded category type a menu draws its vocabulary from.

        Looked up by the pinned id first, falling back to the slug so a
        database that re-seeded the row under a fresh id still resolves.
        """
        taxonomy = await self.types.get(MENU_CATEGORY_TYPE_ID)

        if taxonomy is None:
            taxonomy = await self.types.get_by_slug(MENU_CATEGORY_TYPE_SLUG)

        if taxonomy is None:
            # Seeded by migration, so this means someone removed it. Say what
            # is missing rather than failing on the foreign key later.
            raise ConflictException(
                f"The '{MENU_CATEGORY_TYPE_SLUG}' category type is missing. "
                "Restore it before managing menus."
            )

        return taxonomy

    async def _resolve_menu_category(
        self, category_id: uuid.UUID, *, active: bool = True
    ) -> Category:
        """Fetch a category and insist it is one of the menu categories."""
        taxonomy = await self._taxonomy()
        category = await self.categories.get(category_id)

        if category is None:
            raise BadRequestException(f"Unknown menu category '{category_id}'.")

        if category.category_type_id != taxonomy.id:
            raise BadRequestException(
                f"A menu's category must come from the '{taxonomy.name}' "
                f"category type, and '{category.name}' does not."
            )

        if active and category.status != CategoryStatus.ACTIVE:
            raise BadRequestException(
                f"'{category.name}' is inactive and cannot be assigned to a "
                "menu item."
            )

        return category

    async def _require_parent(
        self, parent_id: uuid.UUID, category_id: uuid.UUID
    ) -> Menu:
        parent = await self.repository.get(parent_id)

        if parent is None:
            raise BadRequestException(f"Unknown parent menu item '{parent_id}'.")

        if parent.menu_category_id != category_id:
            # Otherwise one navigation grows a branch out of another, and a
            # tree read returns items that do not belong to it.
            raise BadRequestException(
                "A menu item's parent must belong to the same menu category."
            )

        return parent

    async def _guard_parent(
        self,
        menu: Menu,
        parent_id: uuid.UUID | None,
        category_id: uuid.UUID,
    ) -> None:
        """Everything that makes a proposed parent unacceptable."""
        if parent_id is None:
            return

        if parent_id == menu.id:
            raise BadRequestException("A menu item cannot be its own parent.")

        parent = await self._require_parent(parent_id, category_id)

        # Moving an item under one of its own descendants would cut that
        # branch out of the tree and leave it pointing round in a ring,
        # reachable from nothing.
        if parent_id in await self.repository.descendant_ids(menu.id):
            raise BadRequestException(
                f"'{parent.title}' sits under '{menu.title}', so it cannot "
                "also be its parent."
            )

        await self._guard_depth(parent)

    async def _guard_depth(self, parent: Menu) -> None:
        depth = len(await self.repository.ancestors_of(parent)) + 2

        if depth > MAX_MENU_DEPTH:
            raise BadRequestException(
                f"Menu items may be nested {MAX_MENU_DEPTH} levels deep at "
                f"most, and this would make {depth}."
            )

    async def _guard_category_move(self, menu: Menu) -> None:
        """Moving an item between navigations takes its branch with it.

        Refused while it has a parent or children, rather than quietly leaving
        half a branch in the old navigation.
        """
        if menu.parent_id is not None:
            raise BadRequestException(
                "Move this item to the top level before changing its menu " "category."
            )

        if await self.repository.count_children(menu.id):
            raise BadRequestException(
                "This item has child items, which would be left behind. Move "
                "them first."
            )
