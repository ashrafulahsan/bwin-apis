"""Business logic for master CRUD records.

The heart of this module is `_resolve_values`. A record's answers are rows in
`master_crud_field_values`, and a foreign key can only say "some field", never
"a field defined on this record's category". That restriction - along with
"every required field was answered" and "the answer parses as its type" - is
what keeps a dynamic form from becoming a bag of unvalidated strings, so it is
checked on every write rather than trusted from the client.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

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
    FALSE_VALUES,
    MASTER_CRUD_SEARCH_FIELDS,
    TRUE_VALUES,
    FieldType,
    MasterCrudStatus,
)
from app.modules.master_cruds.models.master_crud import MasterCrud
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.models.master_crud_field_value import (
    MasterCrudFieldValue,
)
from app.modules.master_cruds.repositories.master_crud import MasterCrudRepository
from app.modules.master_cruds.repositories.master_crud_field import (
    MasterCrudFieldRepository,
)
from app.modules.master_cruds.schemas.master_crud import (
    MasterCrudCreate,
    MasterCrudFieldValueInput,
    MasterCrudUpdate,
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

#: Deliberately permissive: this rejects the typos a form catches, not the
#: addresses that turn out not to receive mail. Only delivery proves that.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

#: One answer, ready to store: the field it belongs to and its normalized text.
ResolvedValue = tuple[MasterCrudField, str | None]


def normalize_field_value(field: MasterCrudField, raw: str | None) -> str | None:
    """Validate an answer against its field's type, and store it one way.

    Normalizing matters as much as validating. `"YES"`, `"1"` and `"true"` all
    mean the same thing to whoever typed them, and storing all three means
    every reader afterwards has to know that. They come out of here as
    `"true"`.

    A blank answer is `None` rather than `""`, so "not answered" is one value
    in the database instead of two.
    """
    if raw is None:
        return None

    trimmed = raw.strip()
    if not trimmed:
        return None

    match field.field_type:
        case FieldType.NUMBER:
            try:
                Decimal(trimmed)
            except InvalidOperation:
                raise BadRequestException(
                    f"'{field.field_name}' expects a number, and "
                    f"'{trimmed}' is not one."
                ) from None
            return trimmed

        case FieldType.DATE:
            try:
                date.fromisoformat(trimmed)
            except ValueError:
                raise BadRequestException(
                    f"'{field.field_name}' expects a date as YYYY-MM-DD, and "
                    f"'{trimmed}' is not one."
                ) from None
            return trimmed

        case FieldType.DATETIME:
            try:
                datetime.fromisoformat(trimmed)
            except ValueError:
                raise BadRequestException(
                    f"'{field.field_name}' expects an ISO 8601 date and time, "
                    f"and '{trimmed}' is not one."
                ) from None
            return trimmed

        case FieldType.BOOLEAN:
            lowered = trimmed.lower()
            if lowered in TRUE_VALUES:
                return "true"
            if lowered in FALSE_VALUES:
                return "false"
            raise BadRequestException(
                f"'{field.field_name}' expects true or false, and "
                f"'{trimmed}' is neither."
            )

        case FieldType.EMAIL:
            if not _EMAIL.match(trimmed):
                raise BadRequestException(
                    f"'{field.field_name}' expects an email address, and "
                    f"'{trimmed}' is not one."
                )
            return trimmed

        case FieldType.URL:
            # The same rule the SEO fields apply, for the same reason: a
            # `javascript:` value ends up rendered straight into an attribute.
            if not trimmed.startswith(("http://", "https://", "/")):
                raise BadRequestException(
                    f"'{field.field_name}' expects a URL starting with "
                    "http://, https:// or /."
                )
            return trimmed

        case _:
            # Text, textarea, and the choice inputs. The options behind a
            # radio or a select are not stored here, so there is nothing to
            # check the answer against beyond its length, which the schema
            # already did.
            return trimmed


class MasterCrudService:
    """Coordinates records and the answers they carry.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MasterCrudRepository(session)
        self.fields = MasterCrudFieldRepository(session)
        self.categories = CategoryRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.MASTER_CRUDS)

    # -- Reads ----------------------------------------------------------

    async def get(self, record_id: uuid.UUID) -> MasterCrud:
        return await self.repository.get_or_raise(record_id)

    async def get_by_slug(self, slug: str) -> MasterCrud:
        found = await self.repository.get_by_slug(slug)
        if found is None:
            raise ConflictException(f"No record has the slug '{slug}'.")
        return found

    async def list_records(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        status: MasterCrudStatus | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[MasterCrud], int]:
        if sort_by is None:
            # Records carry an `order` that counts upwards, so the shared
            # descending default would hand every category back reversed.
            sort_order = SortOrder.ASC

        filters = []

        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if status is not None:
            filters.append(Filter.eq("status", status.value))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(MASTER_CRUD_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def form_for(self, category_id: uuid.UUID) -> list[MasterCrudField]:
        """The fields a record in this category must answer.

        Exposed by this module because writing a record needs the list, and a
        client should not have to hold the field-management permission to fill
        a form in.
        """
        await self._require_category(category_id, active=False)
        return await self.fields.list_for_category(category_id, active_only=True)

    # -- Writes ---------------------------------------------------------

    async def create(
        self, payload: MasterCrudCreate, *, actor_id: uuid.UUID | None = None
    ) -> MasterCrud:
        category = await self._require_category(payload.category_id)
        values = await self._resolve_values(category, payload.field_values)

        slug = await generate_unique_slug(payload.title, self.repository.slug_exists)
        order = payload.order or await self.repository.next_order(category.id)

        created = await self.repository.create(
            title=payload.title,
            slug=slug,
            description=payload.description,
            link=payload.link,
            order=order,
            status=payload.status.value,
            # The related object rather than its id: that leaves the
            # relationship loaded in memory, so rendering the response does
            # not reach for an unloaded `category` and raise MissingGreenlet.
            category=category,
            created_by=actor_id,
            updated_by=actor_id,
            # Built here rather than assigned after the insert. A flushed row
            # counts as persistent, so its `field_values` collection is
            # unloaded and reading it would lazy load - MissingGreenlet, under
            # asyncio. Passing them in means the collection is never unloaded.
            field_values=[
                MasterCrudFieldValue(field=field, value=value)
                for field, value in values
            ],
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=created,
            description=f"Created master CRUD record {created.title!r} in "
            f"{category.name}",
            new_values=snapshot(created) | {"field_values": _describe(values)},
        )
        await self.session.commit()

        logger.info("Created master CRUD record %s (%s)", created.title, created.slug)
        return created

    async def update(
        self,
        record_id: uuid.UUID,
        payload: MasterCrudUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> MasterCrud:
        record = await self.repository.get_or_raise(record_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"field_values"})

        # An explicit `null` on a column that cannot hold one reads as "leave
        # this alone" - a client clearing a form box it never edited.
        for name in ("title", "category_id", "order", "status"):
            if name in changes and changes[name] is None:
                changes.pop(name)

        category_id = changes.get("category_id", record.category_id)
        moving = category_id != record.category_id

        category = record.category
        if moving:
            category = await self._require_category(category_id)
            if payload.field_values is None and await self.repository.count_values(
                record.id
            ):
                # The stored answers belong to the old category's fields, and
                # nothing here can guess their counterparts in the new one.
                raise BadRequestException(
                    f"Moving this record to '{category.name}' means answering "
                    "that category's fields. Send `field_values` with the new "
                    "category."
                )
            changes["category"] = category
            changes.pop("category_id")

        if payload.field_values is not None:
            values = await self._resolve_values(category, payload.field_values)
            await self.repository.set_values(record, values)

        if changes.get("status") is not None:
            changes["status"] = changes["status"].value

        changes["updated_by"] = actor_id

        before = snapshot(record, fields=changes.keys())
        updated = await self.repository.update(record, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if payload.field_values is not None:
            new_values["field_values"] = _describe(values)

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated master CRUD record {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def delete(self, record_id: uuid.UUID) -> None:
        """Soft delete a record, keeping its answers.

        The values are left in place deliberately: they are what a restore
        brings back, and they are why a field that has been answered cannot be
        deleted even after the records answering it are gone.
        """
        record = await self.repository.get_or_raise(record_id)

        before = snapshot(record)
        await self.repository.soft_delete(record)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=record,
            description=f"Deleted master CRUD record {record.title!r}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted master CRUD record %s", record.slug)

    async def restore(self, record_id: uuid.UUID) -> MasterCrud:
        record = await self.repository.get_or_raise(record_id, include_deleted=True)
        restored = await self.repository.restore(record)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored master CRUD record {restored.title!r}",
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
                f"'{category.name}' is inactive and cannot take new records."
            )

        return category

    async def _resolve_values(
        self, category: Category, submitted: Sequence[MasterCrudFieldValueInput]
    ) -> list[ResolvedValue]:
        """Check a form submission against the category's fields.

        Four things are wrong with a submission and all four are caught here:
        answering the same field twice, answering a field that belongs to
        another category, answering a retired field, and leaving a required
        one blank.
        """
        defined = {
            field.id: field
            for field in await self.fields.list_for_category(category.id)
        }

        resolved: list[ResolvedValue] = []
        seen: set[uuid.UUID] = set()

        for answer in submitted:
            field = defined.get(answer.master_crud_field_id)

            if field is None:
                raise BadRequestException(
                    f"'{category.name}' has no field "
                    f"'{answer.master_crud_field_id}'. A record may only "
                    "answer the fields defined on its own category."
                )

            if answer.master_crud_field_id in seen:
                raise BadRequestException(
                    f"'{field.field_name}' was answered twice. A record holds "
                    "one answer per field."
                )
            seen.add(field.id)

            if not field.is_active:
                raise BadRequestException(
                    f"'{field.field_name}' is inactive and is no longer asked "
                    "of new records."
                )

            resolved.append((field, normalize_field_value(field, answer.value)))

        answered = {field.id for field, value in resolved if value is not None}
        missing = [
            field.field_name
            for field in defined.values()
            if field.is_active and field.is_required and field.id not in answered
        ]

        if missing:
            raise BadRequestException(
                f"{', '.join(sorted(missing))} "
                f"{'is' if len(missing) == 1 else 'are'} required by "
                f"'{category.name}'."
            )

        return resolved


def _describe(values: Sequence[ResolvedValue]) -> dict[str, str | None]:
    """Answers keyed by field name, for the activity log.

    Names rather than ids: an audit entry has to be readable years later, by
    which time the id resolves to nothing anyone can look up quickly.
    """
    return {field.field_name: value for field, value in values}
