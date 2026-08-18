"""Data access for menu items."""

import uuid

from sqlalchemy import func, select

from app.modules.menus.constants import FIRST_MENU_ORDER
from app.modules.menus.models.menu import Menu
from app.shared.repositories.base import BaseRepository


class MenuRepository(BaseRepository[Menu]):
    model = Menu
    #: A navigation is read in the order an administrator arranged it, so
    #: `order` is the default rather than `created_at`.
    default_sort_by = "order"

    # -- Tree -----------------------------------------------------------

    async def list_for_category(self, category_id: uuid.UUID) -> list[Menu]:
        """Every live item in one navigation, ordered for building a tree."""
        result = await self.session.execute(
            select(Menu)
            .where(
                Menu.menu_category_id == category_id,
                Menu.deleted_at.is_(None),
            )
            .order_by(Menu.order, Menu.title)
        )
        return list(result.scalars().all())

    async def children_of(self, menu_id: uuid.UUID) -> list[Menu]:
        result = await self.session.execute(
            select(Menu)
            .where(Menu.parent_id == menu_id, Menu.deleted_at.is_(None))
            .order_by(Menu.order, Menu.title)
        )
        return list(result.scalars().all())

    async def count_children(self, menu_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Menu)
            .where(Menu.parent_id == menu_id, Menu.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    async def next_order(
        self, category_id: uuid.UUID, parent_id: uuid.UUID | None
    ) -> int:
        """One past the last of an item's siblings, so a new item goes last.

        Siblings are those sharing both the navigation and the parent - and
        `IS NULL` rather than `= NULL` for the top level, which would match
        nothing and restart every root at 1.
        """
        statement = select(func.max(Menu.order)).where(
            Menu.menu_category_id == category_id,
            Menu.deleted_at.is_(None),
        )
        statement = statement.where(
            Menu.parent_id.is_(None)
            if parent_id is None
            else Menu.parent_id == parent_id
        )

        result = await self.session.execute(statement)
        highest = result.scalar_one_or_none()

        return FIRST_MENU_ORDER if highest is None else highest + 1

    async def ancestors_of(self, menu: Menu) -> list[Menu]:
        """Every item above this one, nearest parent first.

        Walks the parent pointers one query at a time. `MAX_MENU_DEPTH` bounds
        that, and the loop stops on a repeat so a cycle that somehow reached
        the database cannot hang the request.
        """
        seen: set[uuid.UUID] = {menu.id}
        chain: list[Menu] = []
        parent_id = menu.parent_id

        while parent_id is not None and parent_id not in seen:
            parent = await self.get(parent_id)
            if parent is None:
                break

            chain.append(parent)
            seen.add(parent.id)
            parent_id = parent.parent_id

        return chain

    async def descendant_ids(self, menu_id: uuid.UUID) -> set[uuid.UUID]:
        """Every id beneath this item, gathered a level at a time.

        Used to stop an item being moved underneath itself, which would detach
        the whole branch from the tree and leave it pointing in a ring.
        """
        found: set[uuid.UUID] = set()
        frontier = [menu_id]

        while frontier:
            result = await self.session.execute(
                select(Menu.id).where(
                    Menu.parent_id.in_(frontier),
                    Menu.deleted_at.is_(None),
                )
            )
            level = [row for row in result.scalars().all() if row not in found]
            if not level:
                break

            found.update(level)
            frontier = level

        return found
