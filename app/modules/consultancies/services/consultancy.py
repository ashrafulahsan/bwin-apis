"""Business logic for consultancies."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.consultancies.constants import (
    CONSULTANCY_SEARCH_FIELDS,
    ConsultancyStatus,
)
from app.modules.consultancies.models.consultancy import Consultancy
from app.modules.consultancies.repositories.consultancy import ConsultancyRepository
from app.modules.consultancies.schemas.consultancy import (
    ConsultancyCreate,
    ConsultancyUpdate,
)
from app.shared.models.seo import DEFAULT_META_ROBOTS
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.schemas.seo import SEO_FIELDS
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.slug import generate_unique_slug, slugify


class ConsultancyService:
    """Coordinates consultancy reads, writes, and soft deletion."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConsultancyRepository(session)
        self.categories = CategoryRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.CONSULTANCIES)

    async def get(self, consultancy_id: uuid.UUID) -> Consultancy:
        return await self.repository.get_or_raise(consultancy_id)

    async def get_by_slug(self, slug: str) -> Consultancy:
        consultancy = await self.repository.get_by_slug(slug)
        if consultancy is None:
            raise NotFoundException(f"Consultancy '{slug}'")
        return consultancy

    async def list_consultancies(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: ConsultancyStatus | None = None,
        category_id: uuid.UUID | None = None,
        consultancy_type: str | None = None,
        active_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[Consultancy], int]:
        filters = []
        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if consultancy_type is not None:
            filters.append(Filter.eq("consultancy_type", consultancy_type))
        if active_only:
            filters.append(Filter.eq("status", ConsultancyStatus.ACTIVE.value))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(CONSULTANCY_SEARCH_FIELDS),
            sort_by=sort_by or "sort_order",
            sort_order=sort_order,
        )

    async def create(
        self, payload: ConsultancyCreate, *, actor_id: uuid.UUID | None = None
    ) -> Consultancy:
        if await self.repository.code_exists(payload.consultancy_code):
            raise ConflictException(
                f"A consultancy with code '{payload.consultancy_code}' already exists."
            )
        await self._validate_category(payload.category_id)
        values = payload.model_dump(exclude={"seo"})
        values.update(
            {
                "slug": await self._slug_for(payload.slug, payload.title),
                "consultancy_type": payload.consultancy_type.value,
                "status": payload.status.value,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
        )
        values.update(self._seo_values(payload))
        consultancy = await self.repository.create(**values)
        await self.activity.record(
            ActivityAction.CREATE,
            entity=consultancy,
            description=f"Created consultancy {consultancy.title!r}",
            new_values=snapshot(consultancy),
        )
        await self.session.commit()
        return consultancy

    async def update(
        self,
        consultancy_id: uuid.UUID,
        payload: ConsultancyUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Consultancy:
        consultancy = await self.repository.get_or_raise(consultancy_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"seo"})
        if not changes:
            return consultancy

        if (
            "consultancy_code" in changes
            and changes["consultancy_code"] is not None
            and await self.repository.code_exists(
                changes["consultancy_code"], exclude_id=consultancy.id
            )
        ):
            raise ConflictException(
                f"A consultancy with code '{changes['consultancy_code']}' "
                "already exists."
            )
        if "slug" in changes and changes["slug"] is not None:
            changes["slug"] = await self._reslug(consultancy, changes["slug"])
        if "category_id" in changes:
            await self._validate_category(changes["category_id"])
        for field in ("consultancy_type", "status"):
            if field in changes and changes[field] is not None:
                changes[field] = changes[field].value
        if payload.seo is not None:
            changes.update(self._seo_values(payload))
        changes["updated_by"] = actor_id

        before = snapshot(consultancy, fields=changes.keys())
        updated = await self.repository.update(consultancy, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))
        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated consultancy {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )
        await self.session.commit()
        return updated

    async def delete(self, consultancy_id: uuid.UUID) -> None:
        consultancy = await self.repository.get_or_raise(consultancy_id)
        before = snapshot(consultancy)
        await self.repository.soft_delete(consultancy)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=consultancy,
            description=f"Deleted consultancy {consultancy.title!r}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, consultancy_id: uuid.UUID) -> Consultancy:
        consultancy = await self.repository.get_or_raise(
            consultancy_id, include_deleted=True
        )
        restored = await self.repository.restore(consultancy)
        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored consultancy {restored.title!r}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    async def _validate_category(self, category_id: uuid.UUID | None) -> None:
        if category_id is None:
            return
        category = await self.categories.get_or_raise(category_id)
        if not category.is_active:
            raise BadRequestException(f"Category '{category.name}' is inactive.")

    async def _slug_for(self, requested: str | None, title: str) -> str:
        if requested is None:
            return await generate_unique_slug(title, self.repository.slug_exists)
        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if await self.repository.slug_exists(slug):
            raise ConflictException(f"Another consultancy uses the slug '{slug}'.")
        return slug

    async def _reslug(self, consultancy: Consultancy, requested: str) -> str:
        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if slug != consultancy.slug and await self.repository.slug_exists(
            slug, exclude_id=consultancy.id
        ):
            raise ConflictException(f"Another consultancy uses the slug '{slug}'.")
        return slug

    @staticmethod
    def _seo_values(
        payload: ConsultancyCreate | ConsultancyUpdate,
    ) -> dict[str, object]:
        if payload.seo is None:
            return {}
        values = payload.seo.model_dump(exclude_unset=True)
        if values.get("meta_robots") is None:
            values["meta_robots"] = DEFAULT_META_ROBOTS
        return {field: values[field] for field in SEO_FIELDS if field in values}
