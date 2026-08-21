"""Business logic for automations.

Publication is the one thing worth reading before the rest. `status` is not a
field an author can set: going live is a transition, guarded by its own
permission, and it is what decides the publication date.
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
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.automations.constants import (
    AUTOMATION_SEARCH_FIELDS,
    AutomationStatus,
)
from app.modules.automations.models.automation import Automation
from app.modules.automations.repositories.automation import AutomationRepository
from app.modules.automations.schemas.automation import (
    AutomationCreate,
    AutomationUpdate,
)
from app.modules.categories.repositories.category import CategoryRepository
from app.shared.models.seo import DEFAULT_META_ROBOTS
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.schemas.seo import SEO_FIELDS
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.dates import utc_now
from app.shared.utils.slug import generate_unique_slug, slugify

logger = logging.getLogger(__name__)


class AutomationService:
    """Coordinates automation reads, writes and publication transitions.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AutomationRepository(session)
        self.categories = CategoryRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.AUTOMATIONS)

    # -- Reads ----------------------------------------------------------

    async def get(self, automation_id: uuid.UUID) -> Automation:
        return await self.repository.get_or_raise(automation_id)

    async def get_by_slug(self, slug: str) -> Automation:
        automation = await self.repository.get_by_slug(slug)
        if automation is None:
            raise NotFoundException(f"Automation '{slug}'")
        return automation

    async def list_automations(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: AutomationStatus | None = None,
        category_id: uuid.UUID | None = None,
        live_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Automation], int]:
        filters = []
        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if live_only:
            # What a reader should see: published, and not still scheduled.
            # Expressed in SQL rather than by filtering the page afterwards,
            # which would return short pages and a total that disagrees.
            filters.extend(
                [
                    Filter.eq("status", AutomationStatus.PUBLISHED.value),
                    Filter.lte("published_at", utc_now()),
                ]
            )

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(AUTOMATION_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: AutomationCreate, *, actor_id: uuid.UUID | None = None
    ) -> Automation:
        await self._validate_category(payload.category_id)

        values = payload.model_dump(exclude={"seo"})
        values.update(
            {
                "slug": await self._slug_for(payload.slug, payload.title),
                # An automation is always born a draft. Publishing is a
                # separate call with a separate permission, so creating one
                # cannot bypass it.
                "status": AutomationStatus.DRAFT.value,
                "published_at": None,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
        )
        values.update(self._seo_values(payload))
        automation = await self.repository.create(**values)

        await self.activity.record(
            ActivityAction.CREATE,
            entity=automation,
            description=f"Created automation {automation.title!r}",
            new_values=snapshot(automation, exclude=["description"]),
        )
        await self.session.commit()

        logger.info("Created automation %s (%s)", automation.title, automation.slug)
        return automation

    async def update(
        self,
        automation_id: uuid.UUID,
        payload: AutomationUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Automation:
        automation = await self.repository.get_or_raise(automation_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"seo"})
        if not changes:
            return automation

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form field it never edited. The
        # alternative is a 500 from the NOT NULL constraint.
        for field in ("title", "slug"):
            if field in changes and changes[field] is None:
                changes.pop(field)

        if "slug" in changes:
            changes["slug"] = await self._reslug(automation, changes["slug"])
        if "category_id" in changes:
            await self._validate_category(changes["category_id"])
        if payload.seo is not None:
            changes.update(self._seo_values(payload))
        changes["updated_by"] = actor_id

        # `description` is excluded from both sides: it is prose, and an audit
        # trail holding two copies of it per edit is one nobody can read.
        # That it changed is recorded; the wording lives in the automation.
        before = snapshot(automation, fields=changes.keys(), exclude=["description"])
        updated = await self.repository.update(automation, **changes)
        old_values, new_values = diff(
            before, snapshot(updated, fields=changes.keys(), exclude=["description"])
        )
        if "description" in changes:
            length = len(updated.description or "")
            new_values["description"] = f"{length} characters"

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated automation {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )
        await self.session.commit()
        return updated

    async def publish(
        self,
        automation_id: uuid.UUID,
        *,
        published_at: datetime | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Automation:
        """Take an automation live, now or at a chosen moment.

        One that has been live before keeps its original date unless a new one
        is given: re-publishing something out of the archive should not
        present it as new.
        """
        automation = await self.repository.get_or_raise(automation_id)
        if automation.status == AutomationStatus.PUBLISHED and published_at is None:
            raise ConflictException(f"'{automation.title}' is already published.")

        moment = published_at or automation.published_at or utc_now()
        previous_status = automation.status
        updated = await self.repository.update(
            automation,
            status=AutomationStatus.PUBLISHED.value,
            published_at=moment,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.PUBLISH,
            entity=updated,
            description=(
                f"{'Scheduled' if updated.is_scheduled else 'Published'} "
                f"automation {updated.title!r}"
            ),
            old_values={"status": previous_status},
            new_values={
                "status": updated.status,
                "published_at": moment.isoformat(),
                "scheduled": updated.is_scheduled,
            },
        )
        await self.session.commit()

        logger.info("Published automation %s at %s", updated.slug, moment.isoformat())
        return updated

    async def unpublish(
        self, automation_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Automation:
        """Pull an automation back to draft.

        `published_at` is kept, so republishing restores the original date
        rather than presenting an old entry as new.
        """
        automation = await self.repository.get_or_raise(automation_id)
        if automation.status == AutomationStatus.DRAFT:
            raise ConflictException(f"'{automation.title}' is already a draft.")

        previous_status = automation.status
        updated = await self.repository.update(
            automation, status=AutomationStatus.DRAFT.value, updated_by=actor_id
        )

        await self.activity.record(
            ActivityAction.UNPUBLISH,
            entity=updated,
            description=f"Pulled automation {updated.title!r} back to draft",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def archive(
        self, automation_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Automation:
        """Retire an automation without deleting it, so its URL resolves."""
        automation = await self.repository.get_or_raise(automation_id)
        if automation.status == AutomationStatus.ARCHIVED:
            raise ConflictException(f"'{automation.title}' is already archived.")

        previous_status = automation.status
        updated = await self.repository.update(
            automation, status=AutomationStatus.ARCHIVED.value, updated_by=actor_id
        )

        await self.activity.record(
            ActivityAction.ARCHIVE,
            entity=updated,
            description=f"Archived automation {updated.title!r}",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def delete(self, automation_id: uuid.UUID) -> None:
        """Soft delete, so the row survives for audit and restore."""
        automation = await self.repository.get_or_raise(automation_id)
        before = snapshot(automation, exclude=["description"])
        await self.repository.soft_delete(automation)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=automation,
            description=f"Deleted automation {automation.title!r}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, automation_id: uuid.UUID) -> Automation:
        automation = await self.repository.get_or_raise(
            automation_id, include_deleted=True
        )
        restored = await self.repository.restore(automation)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored automation {restored.title!r}",
            new_values=snapshot(restored, exclude=["description"]),
        )
        await self.session.commit()
        return restored

    # -- Categories -----------------------------------------------------

    async def _validate_category(self, category_id: uuid.UUID | None) -> None:
        if category_id is None:
            return
        category = await self.categories.get_or_raise(category_id)
        if not category.is_active:
            raise BadRequestException(f"Category '{category.name}' is inactive.")

    # -- Slugs ----------------------------------------------------------

    async def _slug_for(self, requested: str | None, title: str) -> str:
        """Derive a slug from the title, or honour the one asked for.

        A derived slug is quietly suffixed when it collides; a requested one
        is not. An author who asked for a particular URL needs to be told it
        is taken, not handed `-2` and left to find out from the address bar.
        """
        if requested is None:
            return await generate_unique_slug(title, self.repository.slug_exists)

        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if await self.repository.slug_exists(slug):
            raise ConflictException(f"Another automation uses the slug '{slug}'.")
        return slug

    async def _reslug(self, automation: Automation, requested: str) -> str:
        """Change an automation's address, which only a draft may do.

        Once it has been published the slug is out in links, menus and search
        results, and changing it breaks all of them silently.
        """
        if automation.status != AutomationStatus.DRAFT:
            raise ConflictException(
                "The address of a published automation cannot be changed - it "
                "is already in links and search results. Unpublish it first if "
                "that is really what you want."
            )

        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if slug != automation.slug and await self.repository.slug_exists(
            slug, exclude_id=automation.id
        ):
            raise ConflictException(f"Another automation uses the slug '{slug}'.")
        return slug

    # -- SEO ------------------------------------------------------------

    @staticmethod
    def _seo_values(
        payload: AutomationCreate | AutomationUpdate,
    ) -> dict[str, object]:
        """Flatten the nested `seo` object onto the model's own columns.

        Only the keys actually sent are returned, so a partial update of one
        SEO field does not blank the other seven. `meta_robots` cannot hold a
        null and has a meaningful default, so clearing that box is read as
        "back to the default".
        """
        if payload.seo is None:
            return {}

        values = payload.seo.model_dump(exclude_unset=True)
        if "meta_robots" in values and values["meta_robots"] is None:
            values["meta_robots"] = DEFAULT_META_ROBOTS

        return {field: values[field] for field in SEO_FIELDS if field in values}
