"""Data access for automations."""

import uuid

from sqlalchemy import select

from app.modules.automations.models.automation import Automation
from app.shared.repositories.base import BaseRepository


class AutomationRepository(BaseRepository[Automation]):
    model = Automation

    async def get_by_slug(self, slug: str) -> Automation | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(
        self, slug: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Automation.slug == slug]
        if exclude_id is not None:
            conditions.append(Automation.id != exclude_id)
        result = await self.session.execute(
            select(select(Automation.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())
