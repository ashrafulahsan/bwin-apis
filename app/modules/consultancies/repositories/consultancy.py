"""Data access for consultancies."""

import uuid

from sqlalchemy import select

from app.modules.consultancies.models.consultancy import Consultancy
from app.shared.repositories.base import BaseRepository


class ConsultancyRepository(BaseRepository[Consultancy]):
    model = Consultancy

    async def get_by_slug(self, slug: str) -> Consultancy | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(
        self, slug: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Consultancy.slug == slug]
        if exclude_id is not None:
            conditions.append(Consultancy.id != exclude_id)
        result = await self.session.execute(
            select(select(Consultancy.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def code_exists(
        self, code: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Consultancy.consultancy_code == code]
        if exclude_id is not None:
            conditions.append(Consultancy.id != exclude_id)
        result = await self.session.execute(
            select(select(Consultancy.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())
