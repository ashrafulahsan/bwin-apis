"""Request and response schemas for users."""

import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.core.constants import Language
from app.core.security import BCRYPT_MAX_BYTES, password_byte_length
from app.modules.roles.schemas.role import RoleSummary
from app.modules.users.constants import (
    NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    PROVIDER_USER_ID_MAX_LENGTH,
    AuthProvider,
    UserStatus,
    normalize_email,
    normalize_phone,
)

MIN_PASSWORD_LENGTH = 8


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    # bcrypt ignores anything past 72 bytes, which would let two different
    # passwords open the same account. Refuse rather than truncate.
    if password_byte_length(value) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes. "
            "Accented and non-Latin characters use several bytes each."
        )

    return value


def _validate_phone(value: str | None) -> str | None:
    return normalize_phone(value) if value else None


def _validate_email(value: str | None) -> str | None:
    return normalize_email(value) if value else None


class UserBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    last_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    avatar_url: str | None = None
    bio: str | None = None
    language: Language = Language.EN


class UserCreate(UserBase):
    """Payload for creating a user.

    Either `email` or `phone` is required - both are accepted, and either can
    then be used to sign in.
    """

    email: EmailStr | None = Field(default=None, examples=["ali@example.com"])
    phone: str | None = Field(
        default=None,
        max_length=PHONE_MAX_LENGTH,
        description="Local or international format; stored as E.164.",
        examples=["+8801712345678", "01712345678"],
    )
    password: str | None = Field(
        default=None,
        description="Optional: omit for an account that only uses social login.",
    )
    status: UserStatus = UserStatus.PENDING
    role_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return _validate_email(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return _validate_phone(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str | None) -> str | None:
        return _validate_password(value) if value is not None else None

    @model_validator(mode="after")
    def require_an_identifier(self) -> Self:
        if not self.email and not self.phone:
            raise ValueError("An email address or a phone number is required.")
        return self


class UserUpdate(BaseModel):
    """Partial update. Passwords change through their own endpoint."""

    first_name: str | None = Field(
        default=None, min_length=1, max_length=NAME_MAX_LENGTH
    )
    last_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=PHONE_MAX_LENGTH)
    avatar_url: str | None = None
    bio: str | None = None
    language: Language | None = None
    status: UserStatus | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return _validate_email(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return _validate_phone(value)


class PasswordSet(BaseModel):
    """Set or replace a password.

    `current_password` may be omitted only for an account that has none yet,
    such as one created through Google.
    """

    current_password: str | None = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)


class UserIdentityRead(BaseModel):
    """A linked social account."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    provider_user_id: str
    email: str | None
    created_at: datetime


class UserRead(BaseModel):
    """A user as returned by the API. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    phone: str | None
    first_name: str
    last_name: str | None
    full_name: str
    avatar_url: str | None
    bio: str | None
    status: str
    language: str
    email_verified: bool
    phone_verified: bool
    has_password: bool
    last_login_at: datetime | None
    roles: list[RoleSummary]
    identities: list[UserIdentityRead]
    created_at: datetime
    updated_at: datetime


class UserSummary(BaseModel):
    """Compact form for lists and embedding."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    phone: str | None
    full_name: str
    avatar_url: str | None
    status: str


class UserRoleAssignment(BaseModel):
    """Roles to grant, revoke, or set as the complete list."""

    role_ids: list[uuid.UUID] = Field(min_length=1)


class SocialLogin(BaseModel):
    """Identity handed back by Google or Facebook.

    The caller is responsible for having verified this with the provider -
    exchanging the authorization code and validating the token happens in the
    authentication module.
    """

    provider: AuthProvider = Field(examples=["google", "facebook"])
    provider_user_id: str = Field(
        min_length=1,
        max_length=PROVIDER_USER_ID_MAX_LENGTH,
        description="The provider's stable identifier for this account.",
    )
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    last_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    avatar_url: str | None = None

    @field_validator("provider")
    @classmethod
    def check_provider_is_social(cls, value: AuthProvider) -> AuthProvider:
        if value is AuthProvider.PASSWORD:
            raise ValueError("`password` is not a social provider.")
        return value

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return _validate_email(value)


class IdentifierLookup(BaseModel):
    """A sign-in identifier: either an email address or a phone number."""

    identifier: str = Field(
        min_length=1,
        description="Email address or phone number.",
        examples=["ali@example.com", "+8801712345678"],
    )

    def normalized(self) -> dict[str, Any]:
        return {"identifier": self.identifier.strip()}
