"""Data access for roles."""

import uuid

from sqlalchemy import func, select

from app.modules.roles.models.role import Role
from app.shared.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    model = Role
    default_sort_by = "level"

    async def get_by_slug(self, slug: str) -> Role | None:
        return await self.get_by_field("slug", slug)

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Role | None:
        """Case-insensitive lookup, so `admin` collides with `Admin`."""
        conditions = [func.lower(Role.name) == name.lower()]
        if not include_deleted:
            conditions.append(Role.deleted_at.is_(None))

        result = await self.session.execute(select(Role).where(*conditions))
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        """Callback for `generate_unique_slug`.

        Includes soft-deleted rows: the column is uniquely constrained at the
        database level, so a deleted role still occupies its slug.
        """
        statement = select(select(Role.id).where(Role.slug == slug).exists())
        result = await self.session.execute(statement)
        return bool(result.scalar_one())

    async def name_exists(
        self, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        """Whether another role already uses this name.

        Counts soft-deleted rows, matching the database's unique constraint -
        otherwise the caller would sail past this check into an
        `IntegrityError` instead of a clean conflict.
        """
        conditions = [func.lower(Role.name) == name.lower()]
        if exclude_id is not None:
            conditions.append(Role.id != exclude_id)

        statement = select(select(Role.id).where(*conditions).exists())
        result = await self.session.execute(statement)
        return bool(result.scalar_one())

    async def list_all(self) -> list[Role]:
        """Every active role, most privileged first. Used to populate pickers."""
        return await self.list(sort_by="level")
