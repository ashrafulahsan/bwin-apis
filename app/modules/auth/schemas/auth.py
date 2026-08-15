"""Request and response schemas for authentication."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.constants import BEARER_SCHEME
from app.modules.users.schemas.user import UserRead, validate_password


class LoginRequest(BaseModel):
    """Sign in with a password.

    `identifier` is whichever credential the user has: an email address or a
    phone number. Which one it is is worked out from the value, so the client
    only needs one field.
    """

    identifier: str = Field(
        min_length=1,
        max_length=255,
        description="Email address or phone number.",
        examples=["student@bwin.example.com", "01700000007"],
    )
    password: str = Field(min_length=1, examples=["BwinDemo#2026"])


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a new pair."""

    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    """End one session.

    The refresh token identifies which session to end. Without it the access
    token alone cannot say which of a user's devices is signing out.
    """

    refresh_token: str = Field(min_length=1)


class ForgotPasswordRequest(BaseModel):
    """Ask for a reset link.

    Takes the same identifier as sign-in, so someone who registered with a
    phone number does not have to remember whether they also gave an address.
    """

    identifier: str = Field(
        min_length=1,
        max_length=255,
        description="Email address or phone number.",
        examples=["student@bwin.example.com", "01700000007"],
    )


class ResetPasswordRequest(BaseModel):
    """Spend a reset link and set a new password."""

    token: str = Field(min_length=1, description="The token from the reset link.")
    new_password: str = Field(examples=["a-new-passphrase"])

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password(value)


class ResetTokenCheck(BaseModel):
    """Check a token before showing the form behind it."""

    token: str = Field(min_length=1)


class ResetTokenStatus(BaseModel):
    """Whether a reset link is still worth showing a form for."""

    valid: bool
    #: Present only when valid, and partly hidden. Enough for the page to say
    #: whose password is being reset without naming the account to whoever
    #: happens to hold the link.
    masked_identifier: str | None = None


class ChangePasswordRequest(BaseModel):
    """Change your own password while signed in."""

    current_password: str | None = Field(
        default=None,
        description=(
            "Required when the account already has a password. An account "
            "created through Google has none, and can set its first without."
        ),
    )
    new_password: str
    sign_out_other_sessions: bool = Field(
        default=True,
        description="End every other session. Leave on unless you know why not.",
    )

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password(value)


class PasswordChanged(BaseModel):
    """The outcome of changing your own password."""

    sessions_ended: int
    tokens: "TokenPair | None" = Field(
        default=None,
        description=(
            "A replacement pair. The change retires every token the account "
            "held, including the one that made this request, so a client that "
            "wants to stay signed in should swap to these."
        ),
    )


class TokenPair(BaseModel):
    """What a successful sign-in returns."""

    access_token: str
    refresh_token: str
    token_type: str = Field(
        default=BEARER_SCHEME, description="Always `Bearer`, per RFC 6750."
    )
    expires_in: int = Field(
        description="Seconds until the access token expires.", examples=[1800]
    )
    expires_at: datetime = Field(description="When the access token expires, in UTC.")
    refresh_expires_at: datetime = Field(
        description="When the refresh token expires, in UTC."
    )


class AuthenticatedUser(BaseModel):
    """Tokens plus the account they belong to.

    The user comes back with the tokens so a client can render the signed-in
    state without a second round trip.
    """

    user: UserRead
    tokens: TokenPair
    roles: list[str] = Field(description="Slugs of every role held.")
    permissions: list[str] = Field(
        description="Every permission code the roles add up to."
    )


class SessionRead(BaseModel):
    """One signed-in session, as shown to the user it belongs to."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    user_agent: str | None
    ip_address: str | None
    is_active: bool


class SessionContext(BaseModel):
    """Where a sign-in came from, recorded against the session it creates."""

    user_agent: str | None = None
    ip_address: str | None = None


# `PasswordChanged` names `TokenPair` before it is defined.
PasswordChanged.model_rebuild()
