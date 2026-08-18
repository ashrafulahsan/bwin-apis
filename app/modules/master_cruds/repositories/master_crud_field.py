"""Data access for master CRUD fields."""

import uuid

from sqlalchemy import func, select

from app.modules.master_cruds.constants import MasterCrudStatus
from app.modules.master_cruds.models.master_crud_field import MasterCrudField
from app.modules.master_cruds.models.master_crud_field_value import MasterCrudFieldValue
from app.shared.repositories.base import BaseRepository


class MasterCrudFieldRepository(BaseRepository[MasterCrudField]):
    model = MasterCrudField
    default_sort_by = "field_name"

    async def list_for_category(
        self, category_id: uuid.UUID, *, active_only: bool = False
    ) -> list[MasterCrudField]:
        """Every live field on a category, in the order a form asks them."""
        conditions = [
            MasterCrudField.category_id == category_id,
            MasterCrudField.deleted_at.is_(None),
        ]
        if active_only:
            conditions.append(MasterCrudField.status == MasterCrudStatus.ACTIVE.value)

        result = await self.session.execute(
            select(MasterCrudField)
            .where(*conditions)
            .order_by(MasterCrudField.field_name)
        )
        return list(result.scalars().all())

    async def name_exists_in_category(
        self,
        field_name: str,
        category_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """Matches the unique constraint on `(category_id, field_name)`."""
        conditions = [
            MasterCrudField.field_name == field_name,
            MasterCrudField.category_id == category_id,
        ]
        if exclude_id is not None:
            conditions.append(MasterCrudField.id != exclude_id)

        result = await self.session.execute(
            select(select(MasterCrudField.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def count_values(self, field_id: uuid.UUID) -> int:
        """How many stored answers reference a field.

        Soft-deleted records are counted too. Their values are still rows, the
        foreign key is `RESTRICT`, and a record that can be restored must find
        its field definition still there when it is.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(MasterCrudFieldValue)
            .where(MasterCrudFieldValue.master_crud_field_id == field_id)
        )
        return int(result.scalar_one())
