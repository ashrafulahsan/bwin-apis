"""Data access for blog posts."""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select

from app.core.constants import SortOrder
from app.modules.blogs.constants import BLOG_SEARCH_FIELDS
from app.modules.blogs.models.blog import Blog
from app.modules.blogs.models.blog_tag import blog_tags
from app.shared.repositories.base import BaseRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.utils.pagination import calculate_offset


class BlogRepository(BaseRepository[Blog]):
    model = Blog
    default_sort_by = "created_at"

    async def get_by_slug(self, slug: str) -> Blog | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(
        self, slug: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        conditions = [Blog.slug == slug]
        if exclude_id is not None:
            conditions.append(Blog.id != exclude_id)

        result = await self.session.execute(
            select(select(Blog.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def search(
        self,
        pagination: SupportsPagination,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        tag_id: uuid.UUID | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Blog], int]:
        """One page of posts plus the total, with an optional tag filter.

        The base `paginate` would serve everything here except the tag, which
        lives in an association table. It is applied as an `EXISTS` rather
        than a join: a join through a many-to-many multiplies the rows, so
        the count would report a post once per matching tag.
        """
        conditions = self._conditions(
            filters=filters, search=search, search_fields=list(BLOG_SEARCH_FIELDS)
        )

        if tag_id is not None:
            conditions.append(
                select(blog_tags.c.id)
                .where(blog_tags.c.blog_id == Blog.id, blog_tags.c.tag_id == tag_id)
                .exists()
            )

        total = await self.session.execute(
            select(func.count()).select_from(Blog).where(*conditions)
        )

        statement = self._apply_ordering(
            select(Blog).where(*conditions), sort_by, sort_order
        )
        rows = await self.session.execute(
            statement.offset(
                calculate_offset(pagination.page, pagination.page_size)
            ).limit(pagination.page_size)
        )

        return list(rows.scalars().all()), int(total.scalar_one())

    # -- Tags -----------------------------------------------------------

    async def count_tagged(self, tag_id: uuid.UUID) -> int:
        """How many live posts carry a tag, for "in use" checks."""
        result = await self.session.execute(
            select(func.count())
            .select_from(blog_tags)
            .join(Blog, Blog.id == blog_tags.c.blog_id)
            .where(blog_tags.c.tag_id == tag_id, Blog.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    async def count_in_category(self, category_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Blog)
            .where(Blog.blog_category_id == category_id, Blog.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    async def set_tags(self, blog: Blog, tags: Sequence[object]) -> None:
        """Replace a post's tags with exactly `tags`.

        Assigning to the collection lets the unit of work work out which links
        to add and which to remove, so unchanged tags keep their `created_at`
        instead of being deleted and reinserted on every save.
        """
        blog.tags[:] = list(tags)
        await self.session.flush()
