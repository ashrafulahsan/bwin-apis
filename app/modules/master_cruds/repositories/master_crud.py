"""Data access for master CRUD records."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.modules.master_cruds.constants import FIRST_MASTER_CRUD_ORDER
from app.modules.master_cruds.models.master_crud import MasterCrud
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.models.master_crud_field_value import MasterCrudFieldValue
from app.shared.repositories.base import BaseRepository


class MasterCrudRepository(BaseRepository[MasterCrud]):
    model = MasterCrud
    #: Records are read in the order an administrator arranged them.
    default_sort_by = "order"

    async def get_by_slug(self, slug: str) -> MasterCrud | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(self, slug: str) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        result = await self.session.execute(
            select(select(MasterCrud.id).where(MasterCrud.slug == slug).exists())
        )
        return bool(result.scalar_one())

    async def next_order(self, category_id: uuid.UUID) -> int:
        """One past the last record in a category, so a new one goes last."""
        result = await self.session.execute(
            select(func.max(MasterCrud.order)).where(
                MasterCrud.category_id == category_id,
                MasterCrud.deleted_at.is_(None),
            )
        )
        highest = result.scalar_one_or_none()

        return FIRST_MASTER_CRUD_ORDER if highest is None else highest + 1

    async def count_in_category(self, category_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(MasterCrud)
            .where(
                MasterCrud.category_id == category_id,
                MasterCrud.deleted_at.is_(None),
            )
        )
        return int(result.scalar_one())

    async def count_values(self, master_crud_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(MasterCrudFieldValue)
            .where(MasterCrudFieldValue.master_crud_id == master_crud_id)
        )
        return int(result.scalar_one())

    # -- Values ---------------------------------------------------------

    async def set_values(
        self, record: MasterCrud, values: Sequence[tuple[MasterCrudField, str | None]]
    ) -> None:
        """Replace a loaded record's answers with exactly `values`.

        For updates: the record must have been read by query, so its
        `field_values` are loaded. A freshly inserted row has them unloaded,
        and gets its answers passed to `create()` instead.

        Takes the field objects rather than their ids, and assigns them to the
        relationship: a value built from a bare `master_crud_field_id` has its
        `field` unloaded, and rendering the response would reach for it and
        raise MissingGreenlet.

        Answers that are still asked for are updated in place rather than
        deleted and reinserted, so an untouched value keeps its id and its
        `created_at` - which is what makes the history of one form field
        readable across edits.
        """
        existing = {value.master_crud_field_id: value for value in record.field_values}
        wanted = {field.id for field, _ in values}

        for field, value in values:
            stored = existing.get(field.id)
            if stored is None:
                record.field_values.append(
                    MasterCrudFieldValue(field=field, value=value)
                )
            elif stored.value != value:
                stored.value = value

        # `delete-orphan` on the relationship turns removal from the
        # collection into a DELETE, so a field dropped from the form does not
        # leave an answer behind.
        for field_id, stored in existing.items():
            if field_id not in wanted:
                record.field_values.remove(stored)

        await self.session.flush()
