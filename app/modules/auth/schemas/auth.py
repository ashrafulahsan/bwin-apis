"""Request and response schemas for authentication."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.constants import BEARER_SCHEME
from app.modules.users.schemas.user import UserRead


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
