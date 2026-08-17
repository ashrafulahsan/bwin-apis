"""Business logic for category types."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import ConflictException, NotFoundException
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.categories.schemas.category import (
    CategoryTypeCreate,
    CategoryTypeUpdate,
)
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)
from app.shared.utils.slug import generate_unique_slug

logger = logging.getLogger(__name__)


class CategoryTypeService:
    """Coordinates taxonomy reads and writes.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CategoryTypeRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.CATEGORIES)

    # -- Reads ----------------------------------------------------------

    async def get(self, type_id: uuid.UUID) -> CategoryType:
        return await self.repository.get_or_raise(type_id)

    async def get_by_slug(self, slug: str) -> CategoryType:
        found = await self.repository.get_by_slug(slug)
        if found is None:
            raise NotFoundException(f"Category type '{slug}'")
        return found

    async def list_types(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: CategoryStatus | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[CategoryType], int]:
        filters = []
        if status is not None:
            filters.append(Filter.eq("status", status.value))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["name", "slug", "description"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: CategoryTypeCreate, *, actor_id: uuid.UUID | None = None
    ) -> CategoryType:
        existing = await self.repository.get_by_name(payload.name, include_deleted=True)

        if existing is not None:
            # A soft-deleted row still holds the name at the database level,
            # but an administrator cannot see it in any listing - so say so
            # rather than reporting a conflict with something invisible.
            if existing.deleted_at is not None:
                raise ConflictException(
                    f"A deleted category type named '{payload.name}' still holds "
                    "that name. Restore it, or rename it before reusing the name."
                )
            raise ConflictException(
                f"A category type named '{payload.name}' already exists."
            )

        slug = await generate_unique_slug(payload.name, self.repository.slug_exists)

        created = await self.repository.create(
            name=payload.name,
            slug=slug,
            description=payload.description,
            status=payload.status.value,
            created_by=actor_id,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=created,
            description=f"Created category type {created.name}",
            new_values=snapshot(created),
        )
        await self.session.commit()

        logger.info("Created category type %s (%s)", created.name, created.slug)
        return created

    async def update(
        self,
        type_id: uuid.UUID,
        payload: CategoryTypeUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> CategoryType:
        category_type = await self.repository.get_or_raise(type_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return category_type

        if (
            "name" in changes
            and changes["name"] != category_type.name
            and await self.repository.name_exists(
                changes["name"], exclude_id=category_type.id
            )
        ):
            raise ConflictException(
                f"A category type named '{changes['name']}' already exists."
            )

        if changes.get("status") is not None:
            changes["status"] = changes["status"].value

        # The slug is deliberately left alone when the name changes: it is
        # already in URLs and in whatever has linked to them.
        changes["updated_by"] = actor_id

        before = snapshot(category_type, fields=changes.keys())
        updated = await self.repository.update(category_type, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated category type {updated.name}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def delete(self, type_id: uuid.UUID) -> None:
        """Soft delete a taxonomy, refusing while it still holds categories.

        Deleting it regardless would orphan an entire tree, and the foreign
        key would refuse anyway - as an opaque integrity error rather than
        something an administrator can act on.
        """
        category_type = await self.repository.get_or_raise(type_id)

        in_use = await self.repository.count_categories(category_type.id)
        if in_use:
            raise ConflictException(
                f"'{category_type.name}' still holds {in_use} "
                f"{'category' if in_use == 1 else 'categories'}. "
                "Delete or move them first."
            )

        before = snapshot(category_type)
        await self.repository.soft_delete(category_type)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=category_type,
            description=f"Deleted category type {category_type.name}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted category type %s", category_type.slug)

    async def restore(self, type_id: uuid.UUID) -> CategoryType:
        category_type = await self.repository.get_or_raise(
            type_id, include_deleted=True
        )
        restored = await self.repository.restore(category_type)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored category type {restored.name}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored
