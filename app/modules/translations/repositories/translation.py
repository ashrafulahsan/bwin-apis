"""Data access for translations."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.constants import Language
from app.modules.translations.constants import namespace_of
from app.modules.translations.models.translation import Translation
from app.shared.repositories.base import BaseRepository


class TranslationRepository(BaseRepository[Translation]):
    model = Translation
    default_sort_by = "key"

    async def get_by_key(self, key: str, language: Language) -> Translation | None:
        """Fetch one translation by its natural key."""
        statement = select(Translation).where(
            Translation.key == key, Translation.language == language.value
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_map(
        self, language: Language, *, namespace: str | None = None
    ) -> dict[str, str]:
        """Every key and value for a language, as a flat map.

        Selects only the two columns it needs - a bundle is fetched on every
        page load, so there is no reason to hydrate full ORM objects.
        """
        statement = select(Translation.key, Translation.value).where(
            Translation.language == language.value
        )

        if namespace:
            statement = statement.where(Translation.namespace == namespace)

        result = await self.session.execute(statement)
        return dict(result.all())  # type: ignore[arg-type]

    async def keys_for(self, language: Language) -> set[str]:
        """Every key defined for a language."""
        statement = select(Translation.key).where(
            Translation.language == language.value
        )
        result = await self.session.execute(statement)
        return set(result.scalars().all())

    async def namespaces(self, language: Language | None = None) -> list[str]:
        """Distinct namespaces, for building an admin filter."""
        statement = select(Translation.namespace).distinct()

        if language:
            statement = statement.where(Translation.language == language.value)

        result = await self.session.execute(statement.order_by(Translation.namespace))
        return list(result.scalars().all())

    async def upsert_many(
        self, language: Language, translations: dict[str, str]
    ) -> int:
        """Insert or update many translations in a single statement.

        Uses `ON CONFLICT (key, language)` so re-importing a locale file
        updates the changed strings instead of failing on the unique
        constraint.
        """
        if not translations:
            return 0

        rows: Sequence[dict[str, str]] = [
            {
                "key": key,
                "namespace": namespace_of(key),
                "language": language.value,
                "value": value,
            }
            for key, value in translations.items()
        ]

        statement = pg_insert(Translation).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_translations_key_language",
            set_={
                "value": statement.excluded.value,
                "namespace": statement.excluded.namespace,
                # A Core-level upsert bypasses the ORM's onupdate, so the
                # timestamp has to be set here or it would never move.
                "updated_at": func.now(),
            },
        )

        result = await self.session.execute(statement)
        return result.rowcount

    async def delete_by_key(self, key: str) -> int:
        """Remove a key across every language, returning the rows deleted."""
        result = await self.session.execute(
            delete(Translation).where(Translation.key == key)
        )
        await self.session.flush()
        return result.rowcount
