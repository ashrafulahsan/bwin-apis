"""Request and response schemas for settings."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.settings.constants import (
    SECRET_MASK,
    SETTING_GROUP_MAX_LENGTH,
    SETTING_KEY_MAX_LENGTH,
    SETTING_LABEL_MAX_LENGTH,
    SettingGroup,
    SettingType,
)
from app.modules.settings.models.setting import Setting


class SettingRead(BaseModel):
    """A setting as returned by the API.

    A secret's value is replaced with a mask rather than omitted, so an admin
    screen can show that a credential has been filled in without ever
    receiving it. Built with `from_model` rather than `model_validate`, so the
    masking cannot be skipped by accident.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    value: str | None
    value_type: str
    group: str
    label: str
    description: str | None
    is_secret: bool
    is_system: bool
    is_set: bool = Field(description="Whether a usable value has been filled in.")
    updated_at: datetime

    @classmethod
    def from_model(cls, setting: Setting) -> "SettingRead":
        return cls(
            id=setting.id,
            key=setting.key,
            value=(
                (SECRET_MASK if setting.is_set else None)
                if setting.is_secret
                else setting.value
            ),
            value_type=setting.value_type,
            group=setting.group,
            label=setting.label,
            description=setting.description,
            is_secret=setting.is_secret,
            is_system=setting.is_system,
            is_set=setting.is_set,
            updated_at=setting.updated_at,
        )


class SettingUpdate(BaseModel):
    """Change one setting's value.

    `None` clears it, which is how a provider gets switched off properly
    rather than left half-configured.
    """

    value: str | None = None

    @field_validator("value")
    @classmethod
    def reject_the_mask(cls, value: str | None) -> str | None:
        # An admin screen shows `********` for a secret. Saving the form
        # unchanged would otherwise overwrite the real credential with it.
        if value == SECRET_MASK:
            raise ValueError(
                "That is the placeholder shown for a secret, not its value. "
                "Leave the field alone to keep the current secret."
            )
        return value


class SettingBulkUpdate(BaseModel):
    """Change several settings in one request, as a settings form does."""

    values: dict[str, str | None] = Field(
        min_length=1,
        examples=[{"google_auth_enabled": "true", "google_client_id": "1234.apps..."}],
    )

    @field_validator("values")
    @classmethod
    def reject_the_mask(cls, values: dict[str, str | None]) -> dict[str, str | None]:
        masked = sorted(key for key, value in values.items() if value == SECRET_MASK)
        if masked:
            raise ValueError(
                f"{', '.join(masked)} still hold the placeholder shown for a "
                "secret. Remove them from the request to keep their values."
            )
        return values


class SettingCreate(BaseModel):
    """Add a setting of your own, alongside the ones that ship."""

    key: str = Field(
        min_length=1,
        max_length=SETTING_KEY_MAX_LENGTH,
        pattern=r"^[a-z][a-z0-9_]*$",
        examples=["support_email"],
    )
    value: str | None = None
    value_type: SettingType = SettingType.STRING
    group: str = Field(
        default=SettingGroup.GENERAL.value, max_length=SETTING_GROUP_MAX_LENGTH
    )
    label: str = Field(min_length=1, max_length=SETTING_LABEL_MAX_LENGTH)
    description: str | None = None
    is_secret: bool = False


class ProviderStatus(BaseModel):
    """Whether a social provider is ready to use, without exposing its keys."""

    provider: str
    enabled: bool = Field(description="Whether an administrator switched it on.")
    configured: bool = Field(description="Whether its credentials are filled in.")
    usable: bool = Field(description="Enabled and configured; sign-in will work.")
    callback_url: str | None = None
    missing: list[str] = Field(
        default_factory=list, description="Setting keys still to be filled in."
    )


def public_value(setting: Setting) -> Any:
    """The value as a client may see it, masked when the setting is secret."""
    if setting.is_secret:
        return SECRET_MASK if setting.is_set else None
    return setting.value
