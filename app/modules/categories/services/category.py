"""Business logic for categories.

Most of what is here defends the shape of the tree. A parent pointer is easy
to store and easy to corrupt: nothing in the column stops a category being
made its own grandparent, or being filed under a branch of a different
taxonomy. Those checks live here, because they are the rules of the domain
rather than of the table.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.categories.constants import (
    MAX_CATEGORY_DEPTH,
    CategoryStatus,
)
from app.modules.categories.models.category import Category
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.categories.schemas.category import (
    CategoryCreate,
    CategoryNode,
    CategoryUpdate,
)
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.utils.slug import generate_unique_slug

logger = logging.getLogger(__name__)


class CategoryService:
    """Coordinates category reads, writes and the tree they form."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CategoryRepository(session)
        self.types = CategoryTypeRepository(session)

    # -- Reads ----------------------------------------------------------

    async def get(self, category_id: uuid.UUID) -> Category:
        return await self.repository.get_or_raise(category_id)

    async def get_by_slug(self, slug: str) -> Category:
        found = await self.repository.get_by_slug(slug)
        if found is None:
            raise NotFoundException(f"Category '{slug}'")
        return found

    async def list_categories(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        type_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool = False,
        status: CategoryStatus | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[Category], int]:
        filters = []

        if type_id is not None:
            filters.append(Filter.eq("category_type_id", type_id))
        if status is not None:
            filters.append(Filter.eq("status", status.value))

        if parent_id is not None:
            filters.append(Filter.eq("parent_category_id", parent_id))
        elif roots_only:
            filters.append(Filter.is_null("parent_category_id"))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["name", "slug", "description"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def children_of(self, category_id: uuid.UUID) -> list[Category]:
        category = await self.repository.get_or_raise(category_id)
        return await self.repository.children_of(category.id)

    async def ancestors_of(self, category_id: uuid.UUID) -> list[Category]:
        """The trail from the nearest parent up to the root, for breadcrumbs."""
        category = await self.repository.get_or_raise(category_id)
        return await self.repository.ancestors_of(category)

    async def tree(
        self, type_id: uuid.UUID, *, active_only: bool = False
    ) -> list[CategoryNode]:
        """A taxonomy's whole tree, in one query.

        Built in memory rather than with a recursive query: the rows are few,
        and one flat SELECT plus a pass to link them beats a round trip per
        level.
        """
        await self.types.get_or_raise(type_id)

        rows = await self.repository.list_for_type(type_id, active_only=active_only)

        nodes = {
            row.id: CategoryNode(
                id=row.id,
                name=row.name,
                slug=row.slug,
                description=row.description,
                status=row.status,
                parent_category_id=row.parent_category_id,
            )
            for row in rows
        }

        roots: list[CategoryNode] = []
        for row in rows:
            node = nodes[row.id]
            parent = (
                nodes.get(row.parent_category_id) if row.parent_category_id else None
            )
            # A category whose parent was filtered out - inactive, say - is
            # promoted to a root rather than dropped, so nothing disappears
            # from the menu without being deleted.
            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)

        return roots

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: CategoryCreate, *, actor_id: uuid.UUID | None = None
    ) -> Category:
        category_type = await self._require_type(payload.category_type_id)

        if await self.repository.name_exists_in_type(payload.name, category_type.id):
            raise ConflictException(
                f"'{category_type.name}' already has a category named "
                f"'{payload.name}'."
            )

        if payload.parent_category_id is not None:
            parent = await self._require_parent(
                payload.parent_category_id, category_type.id
            )
            await self._guard_depth(parent)

        slug = await generate_unique_slug(payload.name, self.repository.slug_exists)

        created = await self.repository.create(
            name=payload.name,
            slug=slug,
            description=payload.description,
            category_type_id=category_type.id,
            parent_category_id=payload.parent_category_id,
            status=payload.status.value,
            created_by=actor_id,
            updated_by=actor_id,
        )
        await self.session.commit()

        # `selectin` loads a relationship when the row is *queried*, and this
        # one was just inserted - so `category_type` is still unloaded, and
        # rendering the response would reach for it and raise MissingGreenlet.
        # The refresh runs the loader inside the await where it is safe.
        await self.session.refresh(created)

        logger.info("Created category %s (%s)", created.name, created.slug)
        return created

    async def update(
        self,
        category_id: uuid.UUID,
        payload: CategoryUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Category:
        category = await self.repository.get_or_raise(category_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return category

        type_id = changes.get("category_type_id", category.category_type_id)
        if "category_type_id" in changes:
            await self._require_type(type_id)
            await self._guard_type_move(category, type_id)

        if "name" in changes and await self.repository.name_exists_in_type(
            changes["name"], type_id, exclude_id=category.id
        ):
            raise ConflictException(
                f"That taxonomy already has a category named '{changes['name']}'."
            )

        if "parent_category_id" in changes:
            await self._guard_parent(category, changes["parent_category_id"], type_id)

        if changes.get("status") is not None:
            changes["status"] = changes["status"].value

        changes["updated_by"] = actor_id

        updated = await self.repository.update(category, **changes)
        await self.session.commit()
        return updated

    async def move(
        self,
        category_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Category:
        """Re-parent a category, or promote it to the top level with `None`."""
        category = await self.repository.get_or_raise(category_id)

        await self._guard_parent(category, parent_id, category.category_type_id)

        updated = await self.repository.update(
            category, parent_category_id=parent_id, updated_by=actor_id
        )
        await self.session.commit()

        logger.info("Moved category %s under %s", category.slug, parent_id)
        return updated

    async def delete(self, category_id: uuid.UUID) -> None:
        """Soft delete a category, refusing while it still has children.

        Cascading would silently remove a whole branch on one click. Refusing
        makes the administrator look at what they are about to lose.
        """
        category = await self.repository.get_or_raise(category_id)

        children = await self.repository.count_children(category.id)
        if children:
            raise ConflictException(
                f"'{category.name}' still has {children} "
                f"{'subcategory' if children == 1 else 'subcategories'}. "
                "Delete or move them first."
            )

        await self.repository.soft_delete(category)
        await self.session.commit()

        logger.info("Deleted category %s", category.slug)

    async def restore(self, category_id: uuid.UUID) -> Category:
        category = await self.repository.get_or_raise(category_id, include_deleted=True)
        restored = await self.repository.restore(category)
        await self.session.commit()
        return restored

    # -- Invariants -----------------------------------------------------

    async def _require_type(self, type_id: uuid.UUID) -> object:
        category_type = await self.types.get(type_id)
        if category_type is None:
            raise BadRequestException(f"Unknown category type '{type_id}'.")
        return category_type

    async def _require_parent(
        self, parent_id: uuid.UUID, type_id: uuid.UUID
    ) -> Category:
        parent = await self.repository.get(parent_id)
        if parent is None:
            raise BadRequestException(f"Unknown parent category '{parent_id}'.")

        if parent.category_type_id != type_id:
            # Otherwise a taxonomy grows a branch out of an unrelated one, and
            # a tree read returns categories that do not belong to it.
            raise BadRequestException(
                "A category's parent must belong to the same category type."
            )

        return parent

    async def _guard_parent(
        self,
        category: Category,
        parent_id: uuid.UUID | None,
        type_id: uuid.UUID,
    ) -> None:
        """Everything that makes a proposed parent unacceptable."""
        if parent_id is None:
            return

        if parent_id == category.id:
            raise BadRequestException("A category cannot be its own parent.")

        parent = await self._require_parent(parent_id, type_id)

        # Moving a category under one of its own descendants would cut that
        # branch out of the tree and leave it pointing round in a ring,
        # reachable from nothing.
        if parent_id in await self.repository.descendant_ids(category.id):
            raise BadRequestException(
                f"'{parent.name}' sits under '{category.name}', so it cannot "
                "also be its parent."
            )

        await self._guard_depth(parent)

    async def _guard_depth(self, parent: Category) -> None:
        depth = len(await self.repository.ancestors_of(parent)) + 2

        if depth > MAX_CATEGORY_DEPTH:
            raise BadRequestException(
                f"Categories may be nested {MAX_CATEGORY_DEPTH} levels deep at "
                f"most, and this would make {depth}."
            )

    async def _guard_type_move(self, category: Category, type_id: uuid.UUID) -> None:
        """Moving a category between taxonomies takes its branch with it.

        Refused while it has a parent or children, rather than quietly leaving
        half a branch in the old taxonomy.
        """
        if type_id == category.category_type_id:
            return

        if category.parent_category_id is not None:
            raise BadRequestException(
                "Move this category to the top level before changing its type."
            )

        if await self.repository.count_children(category.id):
            raise BadRequestException(
                "This category has subcategories, which would be left behind. "
                "Move them first."
            )
