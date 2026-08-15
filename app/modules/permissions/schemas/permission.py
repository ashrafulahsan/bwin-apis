"""Request and response schemas for permissions."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.permissions.constants import (
    PERMISSION_CODE_MAX_LENGTH,
    PERMISSION_CODE_PATTERN,
    PERMISSION_NAME_MAX_LENGTH,
)


def _validate_code(value: str) -> str:
    code = value.strip().lower()

    if not PERMISSION_CODE_PATTERN.match(code):
        raise ValueError(
            "Permission codes must be lowercase `resource.action`, "
            "for example 'user.view'."
        )

    return code


class PermissionCreate(BaseModel):
    """Payload for adding a permission. Resource and action come from the code."""

    code: str = Field(
        max_length=PERMISSION_CODE_MAX_LENGTH,
        description="`resource.action` identifier.",
        examples=["user.view", "course.create"],
    )
    name: str | None = Field(
        default=None,
        max_length=PERMISSION_NAME_MAX_LENGTH,
        description="Label shown in the admin grid. Derived from the code if omitted.",
    )
    description: str | None = None

    @field_validator("code")
    @classmethod
    def check_code(cls, value: str) -> str:
        return _validate_code(value)


class PermissionUpdate(BaseModel):
    """Partial update. The code is immutable - authorization depends on it."""

    name: str | None = Field(default=None, max_length=PERMISSION_NAME_MAX_LENGTH)
    description: str | None = None


class PermissionRead(BaseModel):
    """A permission as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    resource: str
    action: str
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class PermissionSummary(BaseModel):
    """Compact form for embedding in role payloads."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    resource: str
    action: str
    name: str


class ResourcePermissions(BaseModel):
    """Every permission for one resource, for rendering a permission matrix."""

    resource: str
    label: str
    permissions: list[PermissionSummary]


class RolePermissions(BaseModel):
    """The permissions currently granted to a role."""

    role_id: uuid.UUID
    role_slug: str
    count: int
    permissions: list[PermissionSummary]


class PermissionCodes(BaseModel):
    """Payload for granting, revoking or replacing a role's permissions."""

    codes: list[str] = Field(
        min_length=1,
        description="Permission codes to act on.",
        examples=[["user.view", "course.create"]],
    )

    @field_validator("codes")
    @classmethod
    def check_codes(cls, value: list[str]) -> list[str]:
        # Deduplicate while preserving order, so a repeated code is not an error.
        seen: dict[str, None] = {}
        for code in value:
            seen[_validate_code(code)] = None
        return list(seen)


class PermissionCheck(BaseModel):
    """Result of asking whether a role holds a permission."""

    role_slug: str
    code: str
    granted: bool
