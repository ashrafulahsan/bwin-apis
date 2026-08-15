"""Translation model: one row per key per language."""

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.translations.constants import (
    TRANSLATION_KEY_MAX_LENGTH,
    TRANSLATION_NAMESPACE_MAX_LENGTH,
)


class Translation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single translated UI string.

    `language` is a plain string rather than a database enum so adding a
    language is a data change, not a schema migration. Values are validated
    against `Language` at the schema and service layers.
    """

    key: Mapped[str] = mapped_column(
        String(TRANSLATION_KEY_MAX_LENGTH),
        nullable=False,
        doc="Dot-namespaced identifier, e.g. `dashboard.title`.",
    )
    namespace: Mapped[str] = mapped_column(
        String(TRANSLATION_NAMESPACE_MAX_LENGTH),
        nullable=False,
        doc="First key segment, derived on write so a screen can fetch its group.",
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # Also the conflict target for the bulk importer's upsert.
        UniqueConstraint("key", "language", name="uq_translations_key_language"),
        # Serving a bundle filters on language and optionally namespace.
        Index("ix_translations_language_namespace", "language", "namespace"),
    )

    def __repr__(self) -> str:
        return f"<Translation {self.key} [{self.language}]>"
