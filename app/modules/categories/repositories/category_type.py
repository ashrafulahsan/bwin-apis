"""Data access for category types."""

import uuid

from sqlalchemy import func, select

from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.shared.repositories.base import BaseRepository


class CategoryTypeRepository(BaseRepository[CategoryType]):
    model = CategoryType
    default_sort_by = "name"

    async def get_by_slug(self, slug: str) -> CategoryType | None:
        return await self.get_by_field("slug", slug)

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> CategoryType | None:
        return await self.get_by_field("name", name, include_deleted=include_deleted)

    async def slug_exists(self, slug: str) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        return await self._exists(CategoryType.slug == slug)

    async def name_exists(
        self, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [CategoryType.name == name]
        if exclude_id is not None:
            conditions.append(CategoryType.id != exclude_id)

        return await self._exists(*conditions)

    async def _exists(self, *conditions: object) -> bool:
        result = await self.session.execute(
            select(select(CategoryType.id).where(*conditions).exists())  # type: ignore[arg-type]
        )
        return bool(result.scalar_one())

    async def count_categories(self, type_id: uuid.UUID) -> int:
        """How many live categories a taxonomy holds.

        Asked before a delete, so the refusal can say what is in the way
        rather than surfacing a foreign key violation.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(Category)
            .where(
                Category.category_type_id == type_id,
                Category.deleted_at.is_(None),
            )
        )
        return int(result.scalar_one())
