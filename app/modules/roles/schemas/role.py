"""Request and response schemas for roles."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.roles.constants import (
    MAX_ROLE_LEVEL,
    MIN_ROLE_LEVEL,
    ROLE_NAME_MAX_LENGTH,
)


def _clean_name(value: str) -> str:
    name = " ".join(value.split())

    if not name:
        raise ValueError("Role name cannot be blank.")

    return name


class RoleCreate(BaseModel):
    """Payload for creating a role. The slug is derived from the name."""

    name: str = Field(
        min_length=1,
        max_length=ROLE_NAME_MAX_LENGTH,
        description="Display name, e.g. `Content Manager`.",
        examples=["Content Manager"],
    )
    description: str | None = Field(default=None, description="What this role is for.")
    level: int = Field(
        default=MIN_ROLE_LEVEL,
        ge=MIN_ROLE_LEVEL,
        le=MAX_ROLE_LEVEL,
        description="Privilege ordering; higher outranks lower.",
    )

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return _clean_name(value)


class RoleUpdate(BaseModel):
    """Partial update. Omitted fields are left untouched.

    The slug is absent by design: it is a stable identifier that code depends
    on, so renaming a role changes only its display name.
    """

    name: str | None = Field(
        default=None, min_length=1, max_length=ROLE_NAME_MAX_LENGTH
    )
    description: str | None = None
    level: int | None = Field(default=None, ge=MIN_ROLE_LEVEL, le=MAX_ROLE_LEVEL)

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class RoleRead(BaseModel):
    """A role as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    level: int
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleSummary(BaseModel):
    """Compact form for embedding in user payloads and pickers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    level: int
