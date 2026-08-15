"""Business logic for translations."""

import logging
import uuid
from pathlib import Path
from string import Formatter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_LANGUAGE, Language, SortOrder
from app.core.exceptions import ConflictException
from app.modules.translations import loader
from app.modules.translations.constants import namespace_of
from app.modules.translations.models.translation import Translation
from app.modules.translations.repositories.translation import TranslationRepository
from app.modules.translations.schemas.translation import (
    TranslationCreate,
    TranslationUpdate,
)
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination

logger = logging.getLogger(__name__)


class TranslationService:
    """Coordinates translation reads, edits and bulk imports.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TranslationRepository(session)

    # -- Reads ----------------------------------------------------------

    async def get_bundle(
        self,
        language: Language,
        *,
        namespace: str | None = None,
        fallback: bool = True,
    ) -> dict[str, str]:
        """Every translation for a language, as a flat map.

        With `fallback`, keys missing from `language` are filled in from the
        default language, so a partly translated interface shows English text
        rather than blanks or raw keys.
        """
        translations: dict[str, str] = {}

        if fallback and language is not DEFAULT_LANGUAGE:
            translations.update(
                await self.repository.get_map(DEFAULT_LANGUAGE, namespace=namespace)
            )

        translations.update(
            await self.repository.get_map(language, namespace=namespace)
        )

        return translations

    async def translate(
        self,
        key: str,
        language: Language,
        *,
        default: str | None = None,
        **params: Any,
    ) -> str:
        """Resolve one key, falling back through language, default, then key.

        Returning the key itself as a last resort is deliberate: a missing
        string shows up as `course.enroll` in the interface, which is obvious
        in review, rather than as an empty space nobody notices.
        """
        translation = await self.repository.get_by_key(key, language)

        if translation is None and language is not DEFAULT_LANGUAGE:
            translation = await self.repository.get_by_key(key, DEFAULT_LANGUAGE)

        text = translation.value if translation else (default or key)

        return _interpolate(text, params) if params else text

    async def list_translations(
        self,
        pagination: SupportsPagination,
        *,
        language: Language | None = None,
        namespace: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[Translation], int]:
        """A page of translations for the admin interface."""
        filters = []
        if language:
            filters.append(Filter.eq("language", language.value))
        if namespace:
            filters.append(Filter.eq("namespace", namespace))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["key", "value"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_namespaces(self, language: Language | None = None) -> list[str]:
        return await self.repository.namespaces(language)

    async def missing_keys(self, language: Language) -> list[str]:
        """Keys defined in the default language but absent from `language`.

        This is the translator's to-do list.
        """
        if language is DEFAULT_LANGUAGE:
            return []

        reference = await self.repository.keys_for(DEFAULT_LANGUAGE)
        translated = await self.repository.keys_for(language)

        return sorted(reference - translated)

    # -- Writes ---------------------------------------------------------

    async def create(self, payload: TranslationCreate) -> Translation:
        existing = await self.repository.get_by_key(payload.key, payload.language)
        if existing is not None:
            raise ConflictException(
                f"'{payload.key}' already has a {payload.language.value} translation."
            )

        translation = await self.repository.create(
            key=payload.key,
            namespace=namespace_of(payload.key),
            language=payload.language.value,
            value=payload.value,
        )
        await self.session.commit()
        return translation

    async def update(
        self, translation_id: uuid.UUID, payload: TranslationUpdate
    ) -> Translation:
        translation = await self.repository.get_or_raise(translation_id)
        updated = await self.repository.update(translation, value=payload.value)
        await self.session.commit()
        return updated

    async def delete(self, translation_id: uuid.UUID) -> None:
        translation = await self.repository.get_or_raise(translation_id)
        await self.repository.delete(translation)
        await self.session.commit()

    async def import_translations(
        self, language: Language, translations: dict[str, str]
    ) -> int:
        """Bulk upsert, so re-importing a locale file updates changed strings."""
        imported = await self.repository.upsert_many(language, translations)
        await self.session.commit()

        logger.info("Imported %d %s translations", imported, language.value)
        return imported

    async def import_locale_file(
        self, language: Language, *, directory: Path | None = None
    ) -> int:
        """Import `locales/<language>.json` into the database."""
        translations = loader.load_language(language, directory=directory)
        return await self.import_translations(language, translations)

    async def sync_all_locales(
        self, *, directory: Path | None = None
    ) -> dict[Language, int]:
        """Import every locale file that exists."""
        results: dict[Language, int] = {}

        for language, translations in loader.load_all_locales(
            directory=directory
        ).items():
            results[language] = await self.import_translations(language, translations)

        return results


def _interpolate(template: str, params: dict[str, Any]) -> str:
    """Fill `{placeholders}`, leaving the template intact if any are missing.

    A translator who drops a placeholder should not cause a `KeyError` in
    production; showing the raw template is the softer failure.
    """
    try:
        return Formatter().vformat(template, (), _SafeParams(params))
    except (IndexError, ValueError):
        return template


class _SafeParams(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        logger.warning("Missing translation parameter '%s'", key)
        return "{" + key + "}"
