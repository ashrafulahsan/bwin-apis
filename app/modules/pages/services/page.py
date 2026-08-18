"""Business logic for pages.

The one thing worth reading before the rest is publication. `status` is not a
field an author can set: going live is a transition, guarded by its own
permission, and it is what decides the publication date. That separation is
the reason the Editor role exists, and it only means anything if the
transition is guarded separately from the edit.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.pages.constants import PAGE_SEARCH_FIELDS, PageStatus
from app.modules.pages.models.page import Page
from app.modules.pages.repositories.page import PageRepository
from app.modules.pages.schemas.page import PageCreate, PageUpdate
from app.shared.models.seo import DEFAULT_META_ROBOTS
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.schemas.seo import SEO_FIELDS
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)
from app.shared.utils.dates import utc_now
from app.shared.utils.slug import generate_unique_slug, slugify

logger = logging.getLogger(__name__)


class PageService:
    """Coordinates page reads, writes and publication.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PageRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.PAGES)

    # -- Reads ----------------------------------------------------------

    async def get(self, page_id: uuid.UUID) -> Page:
        return await self.repository.get_or_raise(page_id)

    async def get_by_slug(self, slug: str) -> Page:
        found = await self.repository.get_by_slug(slug)
        if found is None:
            raise NotFoundException(f"Page '{slug}'")
        return found

    async def list_pages(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: PageStatus | None = None,
        featured_only: bool = False,
        live_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Page], int]:
        filters = []

        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if featured_only:
            filters.append(Filter.eq("is_featured", True))

        if live_only:
            # What a reader should see: published, and not still scheduled.
            # Expressed in SQL rather than by filtering the page afterwards,
            # which would return short pages and a total that disagrees.
            filters.append(Filter.eq("status", PageStatus.PUBLISHED.value))
            filters.append(Filter.lte("published_at", utc_now()))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(PAGE_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: PageCreate, *, actor_id: uuid.UUID | None = None
    ) -> Page:
        slug = await self._slug_for(payload.slug, payload.title)

        created = await self.repository.create(
            title=payload.title,
            slug=slug,
            description=payload.description,
            content=payload.content,
            thumbnail_image=payload.thumbnail_image,
            thumbnail_image_alt=payload.thumbnail_image_alt,
            is_featured=bool(payload.is_featured),
            # A page is always born a draft. Publishing is a separate call
            # with a separate permission, so creating one cannot bypass it.
            status=PageStatus.DRAFT.value,
            published_at=None,
            created_by=actor_id,
            updated_by=actor_id,
            **self._seo_values(payload),
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=created,
            description=f"Created page {created.title!r}",
            new_values=snapshot(created, exclude=["content"]),
        )
        await self.session.commit()

        logger.info("Created page %s (%s)", created.title, created.slug)
        return created

    async def update(
        self,
        page_id: uuid.UUID,
        payload: PageUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Page:
        page = await self.repository.get_or_raise(page_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"seo"})

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form field it never edited. The
        # alternative is a 500 from the NOT NULL constraint.
        for field in ("title", "content", "slug", "is_featured"):
            if field in changes and changes[field] is None:
                changes.pop(field)

        if "slug" in changes:
            changes["slug"] = await self._reslug(page, changes["slug"])

        if payload.seo is not None:
            changes.update(self._seo_values(payload))

        changes["updated_by"] = actor_id

        # `content` is excluded from both sides: a page body is thousands of
        # words, and an audit trail holding two copies of it per edit is one
        # nobody can read and a table nobody can afford. That the content
        # changed is recorded; the wording itself lives in the page.
        before = snapshot(page, fields=changes.keys(), exclude=["content"])
        updated = await self.repository.update(page, **changes)
        old_values, new_values = diff(
            before, snapshot(updated, fields=changes.keys(), exclude=["content"])
        )

        if "content" in changes:
            new_values["content"] = f"{len(updated.content)} characters"

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated page {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def publish(
        self,
        page_id: uuid.UUID,
        *,
        published_at: datetime | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Page:
        """Take a page live, now or at a chosen moment.

        A page that has been live before keeps its original date unless a new
        one is given: re-publishing something out of the archive should not
        present it as new.
        """
        page = await self.repository.get_or_raise(page_id)

        if page.status == PageStatus.PUBLISHED and published_at is None:
            raise ConflictException(f"'{page.title}' is already published.")

        moment = published_at or page.published_at or utc_now()

        previous_status = page.status
        updated = await self.repository.update(
            page,
            status=PageStatus.PUBLISHED.value,
            published_at=moment,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.PUBLISH,
            entity=updated,
            description=(
                f"{'Scheduled' if updated.is_scheduled else 'Published'} "
                f"page {updated.title!r}"
            ),
            old_values={"status": previous_status},
            new_values={
                "status": updated.status,
                "published_at": moment.isoformat(),
                "scheduled": updated.is_scheduled,
            },
        )
        await self.session.commit()

        logger.info("Published page %s at %s", page.slug, moment.isoformat())
        return updated

    async def unpublish(
        self, page_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Page:
        """Pull a page back to draft.

        `published_at` is kept, so republishing restores the original date
        rather than presenting an old page as new.
        """
        page = await self.repository.get_or_raise(page_id)

        if page.status == PageStatus.DRAFT:
            raise ConflictException(f"'{page.title}' is already a draft.")

        previous_status = page.status
        updated = await self.repository.update(
            page, status=PageStatus.DRAFT.value, updated_by=actor_id
        )

        await self.activity.record(
            ActivityAction.UNPUBLISH,
            entity=updated,
            description=f"Pulled page {updated.title!r} back to draft",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()

        logger.info("Unpublished page %s", page.slug)
        return updated

    async def archive(
        self, page_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Page:
        """Retire a page without deleting it, so its URL still resolves."""
        page = await self.repository.get_or_raise(page_id)

        if page.status == PageStatus.ARCHIVED:
            raise ConflictException(f"'{page.title}' is already archived.")

        previous_status = page.status
        updated = await self.repository.update(
            page, status=PageStatus.ARCHIVED.value, updated_by=actor_id
        )

        await self.activity.record(
            ActivityAction.ARCHIVE,
            entity=updated,
            description=f"Archived page {updated.title!r}",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()

        logger.info("Archived page %s", page.slug)
        return updated

    async def delete(self, page_id: uuid.UUID) -> None:
        """Soft delete, so the row survives for audit and restore."""
        page = await self.repository.get_or_raise(page_id)

        before = snapshot(page, exclude=["content"])
        await self.repository.soft_delete(page)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=page,
            description=f"Deleted page {page.title!r}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted page %s", page.slug)

    async def restore(self, page_id: uuid.UUID) -> Page:
        page = await self.repository.get_or_raise(page_id, include_deleted=True)
        restored = await self.repository.restore(page)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored page {restored.title!r}",
            new_values=snapshot(restored, exclude=["content"]),
        )
        await self.session.commit()
        return restored

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
            raise ConflictException(f"Another page already uses the slug '{slug}'.")

        return slug

    async def _reslug(self, page: Page, requested: str) -> str:
        """Change a page's address, which only a draft may do.

        Once a page has been published the slug is out in links, menus and
        search results, and changing it breaks all of them silently.
        """
        if page.status != PageStatus.DRAFT:
            raise ConflictException(
                "The address of a published page cannot be changed - it is "
                "already in links and search results. Unpublish it first if "
                "that is really what you want."
            )

        slug = slugify(requested)
        if not slug:
            raise BadRequestException(
                f"'{requested}' does not contain anything usable in a URL."
            )

        if slug == page.slug:
            return slug

        if await self.repository.slug_exists(slug, exclude_id=page.id):
            raise ConflictException(f"Another page already uses the slug '{slug}'.")

        return slug

    # -- SEO ------------------------------------------------------------

    @staticmethod
    def _seo_values(payload: PageCreate | PageUpdate) -> dict[str, object]:
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
