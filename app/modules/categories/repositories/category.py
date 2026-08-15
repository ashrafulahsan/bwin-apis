"""Data access for categories."""

import uuid

from sqlalchemy import func, select

from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.shared.repositories.base import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    model = Category
    default_sort_by = "name"

    async def get_by_slug(self, slug: str) -> Category | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(self, slug: str) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        result = await self.session.execute(
            select(select(Category.id).where(Category.slug == slug).exists())
        )
        return bool(result.scalar_one())

    async def name_exists_in_type(
        self,
        name: str,
        type_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """Matches the unique constraint on `(category_type_id, name)`."""
        conditions = [Category.name == name, Category.category_type_id == type_id]
        if exclude_id is not None:
            conditions.append(Category.id != exclude_id)

        result = await self.session.execute(
            select(select(Category.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    # -- Tree -----------------------------------------------------------

    async def list_for_type(
        self, type_id: uuid.UUID, *, active_only: bool = False
    ) -> list[Category]:
        """Every live category in a taxonomy, ordered for building a tree."""
        conditions = [
            Category.category_type_id == type_id,
            Category.deleted_at.is_(None),
        ]
        if active_only:
            conditions.append(Category.status == CategoryStatus.ACTIVE.value)

        result = await self.session.execute(
            select(Category).where(*conditions).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def children_of(self, category_id: uuid.UUID) -> list[Category]:
        result = await self.session.execute(
            select(Category)
            .where(
                Category.parent_category_id == category_id,
                Category.deleted_at.is_(None),
            )
            .order_by(Category.name)
        )
        return list(result.scalars().all())

    async def count_children(self, category_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Category)
            .where(
                Category.parent_category_id == category_id,
                Category.deleted_at.is_(None),
            )
        )
        return int(result.scalar_one())

    async def ancestors_of(self, category: Category) -> list[Category]:
        """Every category above this one, nearest parent first.

        Walks the parent pointers one query at a time. `MAX_CATEGORY_DEPTH`
        bounds that, and the loop stops on a repeat so a cycle that somehow
        reached the database cannot hang the request.
        """
        seen: set[uuid.UUID] = {category.id}
        chain: list[Category] = []
        parent_id = category.parent_category_id

        while parent_id is not None and parent_id not in seen:
            parent = await self.get(parent_id)
            if parent is None:
                break

            chain.append(parent)
            seen.add(parent.id)
            parent_id = parent.parent_category_id

        return chain

    async def descendant_ids(self, category_id: uuid.UUID) -> set[uuid.UUID]:
        """Every id beneath this category, gathered a level at a time.

        Used to stop a category being moved underneath itself, which would
        detach the whole branch from the tree and leave it pointing in a ring.
        """
        found: set[uuid.UUID] = set()
        frontier = [category_id]

        while frontier:
            result = await self.session.execute(
                select(Category.id).where(
                    Category.parent_category_id.in_(frontier),
                    Category.deleted_at.is_(None),
                )
            )
            level = [row for row in result.scalars().all() if row not in found]
            if not level:
                break

            found.update(level)
            frontier = level

        return found
