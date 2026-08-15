"""Business logic for settings."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.settings.constants import (
    SYSTEM_SETTINGS,
    SettingKey,
    SettingType,
)
from app.modules.settings.models.setting import Setting
from app.modules.settings.repositories.setting import SettingRepository
from app.modules.settings.schemas.setting import SettingCreate

logger = logging.getLogger(__name__)


class SettingService:
    """Reads and writes runtime configuration.

    Values are cached for the lifetime of one service instance, which is one
    request. Caching for longer would mean an administrator changing a setting
    could not tell whether it had taken effect; caching not at all would mean
    re-reading the same four OAuth rows several times within a single sign-in.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SettingRepository(session)
        self._cache: dict[str, Setting] = {}

    # -- Reads ----------------------------------------------------------

    async def get(self, key: str) -> Setting:
        setting = await self._load(key)
        if setting is None:
            raise NotFoundException(f"Setting '{key}'")
        return setting

    async def _load(self, key: str) -> Setting | None:
        if key not in self._cache:
            setting = await self.repository.get_by_key(key)
            if setting is None:
                return None
            self._cache[key] = setting
        return self._cache[key]

    async def preload(self, *keys: str) -> None:
        """Fetch several settings in one query, ready for the accessors below."""
        missing = [key for key in keys if key not in self._cache]
        if missing:
            self._cache.update(await self.repository.get_many(missing))

    async def value(self, key: str, default: str | None = None) -> str | None:
        """A setting's text value, or `default` when unset or absent.

        Returning a default rather than raising is deliberate: a missing
        setting should leave a feature switched off, not break the request
        that happened to read it.
        """
        setting = await self._load(key)
        return setting.as_str() if setting is not None else default

    async def flag(self, key: str, default: bool = False) -> bool:
        setting = await self._load(key)
        return setting.as_bool() if setting is not None else default

    async def number(self, key: str, default: int = 0) -> int:
        setting = await self._load(key)
        return setting.as_int(default) if setting is not None else default

    async def require(self, key: str) -> str:
        """A setting that must be filled in for the caller to continue."""
        value = await self.value(key)
        if not value:
            raise BadRequestException(
                f"The '{key}' setting has not been configured yet."
            )
        return value

    async def list_all(self) -> list[Setting]:
        return await self.repository.list_all()

    async def list_group(self, group: str) -> list[Setting]:
        return await self.repository.list_by_group(group)

    # -- Writes ---------------------------------------------------------

    async def set(self, key: str, value: str | None) -> Setting:
        """Change one setting's value."""
        setting = await self.get(key)
        updated = await self.repository.update(setting, value=value)
        await self.session.commit()

        self._cache[key] = updated
        # Never log the value itself - half of these are credentials.
        logger.info("Setting %s updated", key)
        return updated

    async def set_many(self, values: dict[str, str | None]) -> list[Setting]:
        """Change several settings as one unit.

        A settings form saves everything at once, so a bad key must not leave
        half the form applied. Unknown keys are rejected before anything is
        written.
        """
        found = await self.repository.get_many(list(values))

        unknown = sorted(set(values) - set(found))
        if unknown:
            raise NotFoundException(message=f"Unknown settings: {', '.join(unknown)}.")

        updated = []
        for key, value in values.items():
            setting = found[key]
            setting.value = value
            updated.append(setting)

        await self.session.flush()

        # Required, not defensive: the UPDATE expires `updated_at`, which
        # carries a server-side `onupdate`, and reading an expired attribute
        # afterwards triggers lazy IO - which raises `MissingGreenlet` under
        # asyncio, by which point the caller is already rendering a response.
        for setting in updated:
            await self.session.refresh(setting)

        await self.session.commit()

        self._cache.update({setting.key: setting for setting in updated})
        logger.info("Settings updated: %s", ", ".join(sorted(values)))
        return updated

    async def create(self, payload: SettingCreate) -> Setting:
        if await self.repository.key_exists(payload.key):
            raise ConflictException(f"A setting named '{payload.key}' already exists.")

        setting = await self.repository.create(
            key=payload.key,
            value=payload.value,
            value_type=payload.value_type.value,
            group=payload.group,
            label=payload.label,
            description=payload.description,
            is_secret=payload.is_secret,
            is_system=False,
        )
        await self.session.commit()

        logger.info("Created setting %s", setting.key)
        return setting

    async def delete(self, key: str) -> None:
        """Remove a custom setting.

        System settings are refused: the application reads them by name, and
        a missing row would turn a configurable feature into a dead one.
        """
        setting = await self.get(key)

        if setting.is_system:
            raise ForbiddenException(
                f"'{key}' ships with the platform and cannot be deleted. "
                "Clear its value instead."
            )

        await self.repository.delete(setting)
        await self.session.commit()

        self._cache.pop(key, None)
        logger.info("Deleted setting %s", key)

    # -- Seeding --------------------------------------------------------

    async def seed_system_settings(self) -> int:
        """Create any missing built-in setting.

        Idempotent, and existing rows are left alone - re-running this must
        never overwrite credentials an administrator has filled in.
        """
        created = 0

        for definition in SYSTEM_SETTINGS:
            if await self.repository.get_by_key(definition["key"]) is not None:
                continue

            await self.repository.create(
                key=definition["key"],
                value=definition["value"],
                value_type=definition["value_type"],
                group=definition["group"],
                label=definition["label"],
                description=definition["description"],
                is_secret=definition["is_secret"],
                is_system=True,
            )
            created += 1

        if created:
            await self.session.commit()
            logger.info("Seeded %d system settings", created)

        return created


__all__ = ["SettingService", "SettingKey", "SettingType"]
