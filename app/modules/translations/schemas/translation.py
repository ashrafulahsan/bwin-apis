"""Request and response schemas for translations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import Language
from app.modules.translations.constants import (
    TRANSLATION_KEY_MAX_LENGTH,
    TRANSLATION_KEY_PATTERN,
)


def _validate_key(value: str) -> str:
    """Enforce the dot-namespaced key convention."""
    key = value.strip().lower()

    if not TRANSLATION_KEY_PATTERN.match(key):
        raise ValueError(
            "Translation keys must be lowercase and dot-namespaced, "
            "for example 'dashboard.title'."
        )

    return key


class TranslationBase(BaseModel):
    key: str = Field(
        max_length=TRANSLATION_KEY_MAX_LENGTH,
        description="Dot-namespaced identifier, e.g. `dashboard.title`.",
        examples=["dashboard.title", "login.button", "course.enroll"],
    )
    language: Language = Field(description="Language this value is written in.")
    value: str = Field(min_length=1, description="The translated text.")

    @field_validator("key")
    @classmethod
    def check_key(cls, value: str) -> str:
        return _validate_key(value)


class TranslationCreate(TranslationBase):
    """Payload for adding a translation."""


class TranslationUpdate(BaseModel):
    """Payload for editing a translation. Keys and languages are immutable."""

    value: str = Field(min_length=1, description="The translated text.")


class TranslationRead(BaseModel):
    """A translation as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    namespace: str
    language: str
    value: str
    created_at: datetime
    updated_at: datetime


class TranslationBundle(BaseModel):
    """Every key a client needs for one language, as a flat map.

    This is what a frontend fetches once on load.
    """

    language: Language
    namespace: str | None = Field(
        default=None, description="Set when the bundle was narrowed to one group."
    )
    count: int = Field(description="Number of keys in the bundle.")
    translations: dict[str, str] = Field(
        description="Key to translated value.",
        examples=[
            {
                "dashboard.title": "Dashboard",
                "login.button": "Log in",
                "course.enroll": "Enrol",
            }
        ],
    )


class TranslationImport(BaseModel):
    """Bulk upsert payload, accepting flat or nested JSON."""

    language: Language
    translations: dict[str, str] = Field(
        min_length=1, description="Key to translated value."
    )

    @field_validator("translations")
    @classmethod
    def check_keys(cls, value: dict[str, str]) -> dict[str, str]:
        return {_validate_key(key): text for key, text in value.items()}


class TranslationImportResult(BaseModel):
    """Outcome of a bulk import."""

    language: Language
    imported: int = Field(description="Rows inserted or updated.")


class MissingTranslations(BaseModel):
    """Keys present in the default language but absent from another."""

    language: Language
    count: int
    keys: list[str]
