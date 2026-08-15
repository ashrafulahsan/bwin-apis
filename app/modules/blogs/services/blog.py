"""Business logic for blog posts.

Two things here are worth reading before the rest. The first is the pair of
`_resolve_*` methods: a post's category and tags are rows in `categories`, and
a foreign key can only say "some category", not "a category from the
`blog_category` taxonomy". That restriction is the module's central rule, so
it is checked on every write rather than trusted from the client.

The second is publication. `status` is not a field an author can set - going
live is a transition, guarded by its own permission, and it is what decides
the publication date.
"""

import logging
import re
import uuid
from datetime import datetime
from math import ceil

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.blogs.constants import (
    BLOG_CATEGORY_TYPE_SLUG,
    BLOG_TAG_TYPE_SLUG,
    WORDS_PER_MINUTE,
    BlogStatus,
)
from app.modules.blogs.models.blog import Blog
from app.modules.blogs.repositories.blog import BlogRepository
from app.modules.blogs.schemas.blog import BlogCreate, BlogUpdate
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.users.models.user import User
from app.modules.users.repositories.user import UserRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.models.seo import DEFAULT_META_ROBOTS
from app.shared.schemas.seo import SEO_FIELDS
from app.shared.utils.dates import utc_now
from app.shared.utils.slug import generate_unique_slug, slugify

logger = logging.getLogger(__name__)

#: Rough tag stripper, used only for counting words in HTML content.
_MARKUP = re.compile(r"<[^>]+>")


def estimate_reading_minutes(content: str) -> int:
    """Minutes an average reader needs, rounded up and never below one.

    Markup is stripped before counting, so a paragraph wrapped in a dozen
    `<span>`s does not read as a dozen extra words.
    """
    words = len(_MARKUP.sub(" ", content).split())
    return max(1, ceil(words / WORDS_PER_MINUTE))


class BlogService:
    """Coordinates blog reads, writes and publication.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = BlogRepository(session)
        self.categories = CategoryRepository(session)
        self.types = CategoryTypeRepository(session)
        self.users = UserRepository(session)

    # -- Reads ----------------------------------------------------------

    async def get(self, blog_id: uuid.UUID) -> Blog:
        return await self.repository.get_or_raise(blog_id)

    async def get_by_slug(self, slug: str) -> Blog:
        found = await self.repository.get_by_slug(slug)
        if found is None:
            raise NotFoundException(f"Blog post '{slug}'")
        return found

    async def list_blogs(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: BlogStatus | None = None,
        category_id: uuid.UUID | None = None,
        tag_id: uuid.UUID | None = None,
        author_id: uuid.UUID | None = None,
        featured_only: bool = False,
        live_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Blog], int]:
        filters = []

        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if category_id is not None:
            filters.append(Filter.eq("blog_category_id", category_id))
        if author_id is not None:
            filters.append(Filter.eq("author_id", author_id))
        if featured_only:
            filters.append(Filter.eq("is_featured", True))

        if live_only:
            # What a reader should see: published, and not still scheduled.
            # Expressed in SQL rather than by filtering the page afterwards,
            # which would return short pages and a total that disagrees.
            filters.append(Filter.eq("status", BlogStatus.PUBLISHED.value))
            filters.append(Filter.lte("published_at", utc_now()))

        return await self.repository.search(
            pagination,
            filters=filters,
            search=search,
            tag_id=tag_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def available_categories(self) -> list[Category]:
        """The categories a post may be filed under.

        Exposed by the blogs module because writing a post needs this list,
        and the categories endpoints are restricted to administrators.
        """
        return await self._vocabulary(BLOG_CATEGORY_TYPE_SLUG)

    async def available_tags(self) -> list[Category]:
        return await self._vocabulary(BLOG_TAG_TYPE_SLUG)

    async def _vocabulary(self, type_slug: str) -> list[Category]:
        taxonomy = await self._taxonomy(type_slug)
        return await self.categories.list_for_type(taxonomy.id, active_only=True)

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: BlogCreate, *, actor_id: uuid.UUID | None = None
    ) -> Blog:
        category = await self._resolve_category(payload.blog_category_id)
        tags = await self._resolve_tags(payload.tag_ids)
        author = await self._resolve_author(payload.author_id or actor_id)

        slug = await self._slug_for(payload.slug, payload.title)

        created = await self.repository.create(
            title=payload.title,
            slug=slug,
            excerpt=payload.excerpt,
            content=payload.content,
            featured_image_url=payload.featured_image_url,
            featured_image_alt=payload.featured_image_alt,
            is_featured=bool(payload.is_featured),
            reading_minutes=estimate_reading_minutes(payload.content),
            # A post is always born a draft. Publishing is a separate call
            # with a separate permission, so creating one cannot bypass it.
            status=BlogStatus.DRAFT.value,
            published_at=None,
            # The related objects rather than their ids: that leaves the
            # relationships loaded in memory, so rendering the response does
            # not reach for an unloaded `category` and raise MissingGreenlet
            # the way a freshly inserted row otherwise would.
            category=category,
            tags=tags,
            author=author,
            created_by=actor_id,
            updated_by=actor_id,
            **self._seo_values(payload),
        )
        await self.session.commit()

        logger.info("Created blog post %s (%s)", created.title, created.slug)
        return created

    async def update(
        self,
        blog_id: uuid.UUID,
        payload: BlogUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Blog:
        blog = await self.repository.get_or_raise(blog_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"seo", "tag_ids"})

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form field it never edited. The
        # alternative is a 500 from the NOT NULL constraint.
        for field in ("title", "content", "slug", "blog_category_id", "is_featured"):
            if field in changes and changes[field] is None:
                changes.pop(field)

        if "blog_category_id" in changes:
            # Only re-checked when it actually changes: a category retired
            # after the post was filed under it should not block an edit to
            # the post's spelling.
            if changes["blog_category_id"] != blog.blog_category_id:
                changes["category"] = await self._resolve_category(
                    changes["blog_category_id"]
                )
            changes.pop("blog_category_id")

        if "author_id" in changes:
            changes["author"] = await self._resolve_author(changes.pop("author_id"))

        if "slug" in changes:
            changes["slug"] = await self._reslug(blog, changes["slug"])

        if changes.get("content"):
            changes["reading_minutes"] = estimate_reading_minutes(changes["content"])

        if payload.seo is not None:
            changes.update(self._seo_values(payload))

        if payload.tag_ids is not None:
            tags = await self._resolve_tags(payload.tag_ids)
            await self.repository.set_tags(blog, tags)

        changes["updated_by"] = actor_id

        updated = await self.repository.update(blog, **changes)
        await self.session.commit()

        return updated

    async def publish(
        self,
        blog_id: uuid.UUID,
        *,
        published_at: datetime | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Blog:
        """Take a post live, now or at a chosen moment.

        A post that has been live before keeps its original date unless a new
        one is given: re-publishing something out of the archive should not
        move it back to the top of the feed as though it were new.
        """
        blog = await self.repository.get_or_raise(blog_id)

        if blog.status == BlogStatus.PUBLISHED and published_at is None:
            raise ConflictException(f"'{blog.title}' is already published.")

        moment = published_at or blog.published_at or utc_now()

        updated = await self.repository.update(
            blog,
            status=BlogStatus.PUBLISHED.value,
            published_at=moment,
            updated_by=actor_id,
        )
        await self.session.commit()

        logger.info("Published blog post %s at %s", blog.slug, moment.isoformat())
        return updated

    async def unpublish(
        self, blog_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Blog:
        """Pull a post back to draft.

        `published_at` is kept, so republishing restores the original date
        rather than presenting an old post as new.
        """
        blog = await self.repository.get_or_raise(blog_id)

        if blog.status == BlogStatus.DRAFT:
            raise ConflictException(f"'{blog.title}' is already a draft.")

        updated = await self.repository.update(
            blog, status=BlogStatus.DRAFT.value, updated_by=actor_id
        )
        await self.session.commit()

        logger.info("Unpublished blog post %s", blog.slug)
        return updated

    async def archive(
        self, blog_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Blog:
        """Retire a post without deleting it, so its URL still resolves."""
        blog = await self.repository.get_or_raise(blog_id)

        if blog.status == BlogStatus.ARCHIVED:
            raise ConflictException(f"'{blog.title}' is already archived.")

        updated = await self.repository.update(
            blog, status=BlogStatus.ARCHIVED.value, updated_by=actor_id
        )
        await self.session.commit()

        logger.info("Archived blog post %s", blog.slug)
        return updated

    async def delete(self, blog_id: uuid.UUID) -> None:
        """Soft delete, so the row survives for audit and restore."""
        blog = await self.repository.get_or_raise(blog_id)

        await self.repository.soft_delete(blog)
        await self.session.commit()

        logger.info("Deleted blog post %s", blog.slug)

    async def restore(self, blog_id: uuid.UUID) -> Blog:
        blog = await self.repository.get_or_raise(blog_id, include_deleted=True)
        restored = await self.repository.restore(blog)
        await self.session.commit()
        return restored

    # -- Invariants -----------------------------------------------------

    async def _taxonomy(self, slug: str) -> CategoryType:
        """The seeded category type a blog draws its vocabulary from."""
        taxonomy = await self.types.get_by_slug(slug)

        if taxonomy is None:
            # Seeded by migration, so this means someone removed it. Say what
            # is missing rather than failing on the foreign key later.
            raise ConflictException(
                f"The '{slug}' category type is missing. Restore it before "
                "managing blog posts."
            )

        return taxonomy

    async def _resolve_category(self, category_id: uuid.UUID) -> Category:
        taxonomy = await self._taxonomy(BLOG_CATEGORY_TYPE_SLUG)
        category = await self._category_in(category_id, taxonomy, label="category")

        if category.status != CategoryStatus.ACTIVE:
            raise BadRequestException(
                f"'{category.name}' is inactive and cannot be assigned to a post."
            )

        return category

    async def _resolve_tags(self, tag_ids: list[uuid.UUID]) -> list[Category]:
        if not tag_ids:
            return []

        taxonomy = await self._taxonomy(BLOG_TAG_TYPE_SLUG)

        return [
            await self._category_in(tag_id, taxonomy, label="tag") for tag_id in tag_ids
        ]

    async def _category_in(
        self, category_id: uuid.UUID, taxonomy: CategoryType, *, label: str
    ) -> Category:
        """Fetch a category and insist it belongs to `taxonomy`."""
        category = await self.categories.get(category_id)

        if category is None:
            raise BadRequestException(f"Unknown {label} '{category_id}'.")

        if category.category_type_id != taxonomy.id:
            raise BadRequestException(
                f"A blog's {label} must come from the '{taxonomy.name}' "
                f"category type, and '{category.name}' does not."
            )

        return category

    async def _resolve_author(self, author_id: uuid.UUID | None) -> User | None:
        if author_id is None:
            return None

        author = await self.users.get(author_id)
        if author is None:
            raise BadRequestException(f"Unknown author '{author_id}'.")

        return author

    # -- Slugs ----------------------------------------------------------

    async def _slug_for(self, requested: str | None, title: str) -> str:
        """Derive a slug from the title, or honour the one asked for.

        A derived slug is quietly suffixed when it collides; a requested one
        is not. An editor who asked for a particular URL needs to be told it
        is taken, not handed `-2` and left to find out from the address bar.
        """
        if requested is None:
            return await generate_unique_slug(title, self.repository.slug_exists)

        slug = slugify(requested)
        if not slug:
            raise BadRequestException(
                f"'{requested}' does not contain anything usable in a URL."
            )

        if await self.repository.slug_exists(slug):
            raise ConflictException(f"Another post already uses the slug '{slug}'.")

        return slug

    async def _reslug(self, blog: Blog, requested: str) -> str:
        """Change a post's address, which only a draft may do.

        Once a post has been published the slug is out in links, feeds and
        search results, and changing it breaks all of them silently.
        """
        if blog.status != BlogStatus.DRAFT:
            raise ConflictException(
                "The address of a published post cannot be changed - it is "
                "already in links and search results. Unpublish it first if "
                "that is really what you want."
            )

        slug = slugify(requested)
        if not slug:
            raise BadRequestException(
                f"'{requested}' does not contain anything usable in a URL."
            )

        if slug == blog.slug:
            return slug

        if await self.repository.slug_exists(slug, exclude_id=blog.id):
            raise ConflictException(f"Another post already uses the slug '{slug}'.")

        return slug

    # -- SEO ------------------------------------------------------------

    @staticmethod
    def _seo_values(payload: BlogCreate | BlogUpdate) -> dict[str, object]:
        """Flatten the nested `seo` object onto the model's own columns.

        Only the keys actually sent are returned, so a partial update of one
        SEO field does not blank the other seven.

        `meta_robots` is the one column here that cannot hold a null, and it
        is also the one with a meaningful default - so clearing the box is
        read as "back to the default" rather than dropped as unanswerable,
        which is what an author emptying that field is asking for.
        """
        if payload.seo is None:
            return {}

        sent = payload.seo.model_dump(exclude_unset=True)
        if "meta_robots" in sent and sent["meta_robots"] is None:
            sent["meta_robots"] = DEFAULT_META_ROBOTS

        return {field: sent[field] for field in SEO_FIELDS if field in sent}
