"""Data access for pages."""

import uuid

from sqlalchemy import select

from app.modules.pages.models.page import Page
from app.shared.repositories.base import BaseRepository


class PageRepository(BaseRepository[Page]):
    model = Page
    default_sort_by = "created_at"

    async def get_by_slug(self, slug: str) -> Page | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(
        self, slug: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        conditions = [Page.slug == slug]
        if exclude_id is not None:
            conditions.append(Page.id != exclude_id)

        result = await self.session.execute(
            select(select(Page.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())
