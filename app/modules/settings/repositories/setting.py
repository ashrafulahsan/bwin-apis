"""Data access for settings."""

from collections.abc import Sequence

from sqlalchemy import select

from app.modules.settings.models.setting import Setting
from app.shared.repositories.base import BaseRepository


class SettingRepository(BaseRepository[Setting]):
    model = Setting
    default_sort_by = "key"

    async def get_by_key(self, key: str) -> Setting | None:
        return await self.get_by_field("key", key)

    async def get_many(self, keys: Sequence[str]) -> dict[str, Setting]:
        """Fetch several settings at once, keyed by name.

        One query rather than one per key: reading an OAuth provider's
        configuration touches four settings, and doing that per request would
        be four round trips for values that always travel together.
        """
        if not keys:
            return {}

        result = await self.session.execute(
            select(Setting).where(Setting.key.in_(keys))
        )
        return {setting.key: setting for setting in result.scalars().all()}

    async def list_by_group(self, group: str) -> list[Setting]:
        result = await self.session.execute(
            select(Setting).where(Setting.group == group).order_by(Setting.key)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Setting]:
        result = await self.session.execute(select(Setting).order_by(Setting.key))
        return list(result.scalars().all())

    async def key_exists(self, key: str) -> bool:
        result = await self.session.execute(
            select(select(Setting.id).where(Setting.key == key).exists())
        )
        return bool(result.scalar_one())
