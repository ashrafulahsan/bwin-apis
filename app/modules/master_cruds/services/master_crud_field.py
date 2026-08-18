"""Business logic for master CRUD fields.

A field is the schema of a form, so almost everything here defends what
already answered it. Changing a field's category or its type after records
have replied would leave stored values describing a question nobody asked, and
deleting one would leave them describing nothing at all - so all three are
refused while values exist, and the refusal says how many are in the way.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import BadRequestException, ConflictException
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.master_cruds.constants import (
    MASTER_CRUD_FIELD_SEARCH_FIELDS,
    FieldType,
    MasterCrudStatus,
)
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.repositories.master_crud_field import (
    MasterCrudFieldRepository,
)
from app.modules.master_cruds.schemas.master_crud_field import (
    MasterCrudFieldCreate,
    MasterCrudFieldUpdate,
)
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)

logger = logging.getLogger(__name__)


class MasterCrudFieldService:
    """Coordinates the field definitions a category's records answer.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MasterCrudFieldRepository(session)
        self.categories = CategoryRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.MASTER_CRUDS)

    # -- Reads ----------------------------------------------------------

    async def get(self, field_id: uuid.UUID) -> MasterCrudField:
        return await self.repository.get_or_raise(field_id)

    async def list_fields(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        field_type: FieldType | None = None,
        status: MasterCrudStatus | None = None,
        required_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[MasterCrudField], int]:
        filters = []

        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if field_type is not None:
            filters.append(Filter.eq("field_type", field_type.value))
        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if required_only:
            filters.append(Filter.eq("field_requiredness", True))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(MASTER_CRUD_FIELD_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def for_category(
        self, category_id: uuid.UUID, *, active_only: bool = True
    ) -> list[MasterCrudField]:
        """The form a category asks - what a client needs to render one."""
        await self._require_category(category_id, active=False)
        return await self.repository.list_for_category(
            category_id, active_only=active_only
        )

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: MasterCrudFieldCreate, *, actor_id: uuid.UUID | None = None
    ) -> MasterCrudField:
        category = await self._require_category(payload.category_id)

        if await self.repository.name_exists_in_category(
            payload.field_name, category.id
        ):
            raise ConflictException(
                f"'{category.name}' already has a field named "
                f"'{payload.field_name}'."
            )

        created = await self.repository.create(
            field_name=payload.field_name,
            field_type=payload.field_type.value,
            field_requiredness=payload.field_requiredness,
            status=payload.status.value,
            # The related object rather than its id, so `category` is loaded
            # in memory and rendering the response does not reach for an
            # unloaded relationship and raise MissingGreenlet.
            category=category,
            created_by=actor_id,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=created,
            description=(
                f"Created master CRUD field {created.field_name!r} "
                f"on {category.name}"
            ),
            new_values=snapshot(created),
        )
        await self.session.commit()

        logger.info(
            "Created master CRUD field %s on %s", created.field_name, category.name
        )
        return created

    async def update(
        self,
        field_id: uuid.UUID,
        payload: MasterCrudFieldUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> MasterCrudField:
        field = await self.repository.get_or_raise(field_id)
        changes = payload.model_dump(exclude_unset=True)

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form box it never edited.
        for name in ("category_id", "field_name", "field_type", "field_requiredness"):
            if name in changes and changes[name] is None:
                changes.pop(name)

        if not changes:
            return field

        category_id = changes.get("category_id", field.category_id)

        if "category_id" in changes and category_id != field.category_id:
            await self._require_category(category_id)
            await self._guard_answered(
                field,
                "Moving it to another category would leave those answers "
                "attached to a question that category never asked.",
            )

        if "field_type" in changes and changes["field_type"] != field.field_type:
            await self._guard_answered(
                field,
                "Changing its type would leave those answers stored in a "
                "shape the new type cannot read.",
            )

        if "field_name" in changes and await self.repository.name_exists_in_category(
            changes["field_name"], category_id, exclude_id=field.id
        ):
            raise ConflictException(
                f"That category already has a field named "
                f"'{changes['field_name']}'."
            )

        for name in ("field_type", "status"):
            if changes.get(name) is not None:
                changes[name] = changes[name].value

        changes["updated_by"] = actor_id

        before = snapshot(field, fields=changes.keys())
        updated = await self.repository.update(field, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated master CRUD field {updated.field_name!r}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def delete(self, field_id: uuid.UUID) -> None:
        """Soft delete a field, refusing while records have answered it.

        This is the module's central rule. A stored value points at its field
        with a `RESTRICT` foreign key, so the database would refuse a purge
        anyway; refusing here means the caller is told how many answers are in
        the way instead of being handed a constraint violation.
        """
        field = await self.repository.get_or_raise(field_id)

        await self._guard_answered(
            field,
            "Deleting it would leave those answers describing nothing. "
            "Set it inactive instead, or clear the records first.",
        )

        before = snapshot(field)
        await self.repository.soft_delete(field)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=field,
            description=f"Deleted master CRUD field {field.field_name!r}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted master CRUD field %s", field.field_name)

    async def restore(self, field_id: uuid.UUID) -> MasterCrudField:
        field = await self.repository.get_or_raise(field_id, include_deleted=True)
        restored = await self.repository.restore(field)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored master CRUD field {restored.field_name!r}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    # -- Invariants -----------------------------------------------------

    async def _require_category(
        self, category_id: uuid.UUID, *, active: bool = True
    ) -> Category:
        category = await self.categories.get(category_id)

        if category is None:
            raise BadRequestException(f"Unknown category '{category_id}'.")

        if active and category.status != CategoryStatus.ACTIVE:
            raise BadRequestException(
                f"'{category.name}' is inactive and cannot take new fields."
            )

        return category

    async def _guard_answered(self, field: MasterCrudField, consequence: str) -> None:
        """Refuse a change that stored answers cannot survive."""
        answers = await self.repository.count_values(field.id)

        if answers:
            raise ConflictException(
                f"'{field.field_name}' has been answered by {answers} "
                f"{'record' if answers == 1 else 'records'}. {consequence}"
            )
