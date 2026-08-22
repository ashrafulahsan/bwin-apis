"""Request and response schemas for newsletter subscriptions."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.subscriptions.constants import (
    SUBSCRIPTION_NAME_MAX_LENGTH,
    SUBSCRIPTION_REASON_MAX_LENGTH,
    SUBSCRIPTION_SOURCE_MAX_LENGTH,
    SubscriptionStatus,
)


class SubscribeRequest(BaseModel):
    """What the public signup form sends."""

    email: EmailStr = Field(examples=["reader@example.com"])
    name: str | None = Field(default=None, max_length=SUBSCRIPTION_NAME_MAX_LENGTH)
    source: str | None = Field(
        default=None,
        max_length=SUBSCRIPTION_SOURCE_MAX_LENGTH,
        description=(
            "Where the signup happened, for the platform's own reporting - "
            "`footer`, `homepage-popup`, a campaign name. Free text."
        ),
    )

    @field_validator("name", "source")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """An empty box in a form means "not given", not an empty string."""
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ConfirmRequest(BaseModel):
    """The token from a confirmation link."""

    token: str = Field(min_length=1)


class UnsubscribeRequest(BaseModel):
    """The token from a message footer, and optionally why."""

    token: str = Field(min_length=1)
    reason: str | None = Field(
        default=None,
        max_length=SUBSCRIPTION_REASON_MAX_LENGTH,
        description="Optional. Offered, never required - asking is not a gate.",
    )


class SubscriptionCreate(BaseModel):
    """An address an administrator is adding directly.

    No token is issued and no confirmation email goes out: an administrator
    entering an address is asserting that it asked to be here, which is what
    `confirmed_at` will record.
    """

    email: EmailStr
    name: str | None = Field(default=None, max_length=SUBSCRIPTION_NAME_MAX_LENGTH)
    source: str | None = Field(default=None, max_length=SUBSCRIPTION_SOURCE_MAX_LENGTH)


class SubscriptionUpdate(BaseModel):
    """Corrections an administrator can make.

    `status` is absent on purpose. Joining and leaving are transitions with
    their own endpoints and their own audit entries, so "who unsubscribed
    this person, and when?" always has an answer.
    """

    email: EmailStr | None = None
    name: str | None = Field(default=None, max_length=SUBSCRIPTION_NAME_MAX_LENGTH)
    source: str | None = Field(default=None, max_length=SUBSCRIPTION_SOURCE_MAX_LENGTH)


class AdminUnsubscribe(BaseModel):
    """An administrator recording that somebody asked to be taken off."""

    reason: str | None = Field(default=None, max_length=SUBSCRIPTION_REASON_MAX_LENGTH)


class SubscriptionSummary(BaseModel):
    """One row of the admin listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    status: str
    source: str | None
    is_mailable: bool
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SubscriptionRead(SubscriptionSummary):
    """One subscription in full.

    No token appears here, in any form. The confirmation token exists only
    as a digest, the unsubscribe token is derived rather than stored, and
    both are credentials that an admin screen has no use for.
    """

    confirmation_sent_at: datetime | None
    confirmation_expires_at: datetime | None
    unsubscribed_at: datetime | None
    unsubscribe_reason: str | None
    signup_ip: str | None
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    deleted_at: datetime | None


class SubscriptionStats(BaseModel):
    """How big the list is, and what it is made of.

    `mailable` is the number that matters before a send: confirmed addresses
    only, which is not the same as the row count.
    """

    total: int
    mailable: int
    pending: int
    subscribed: int
    unsubscribed: int
    bounced: int

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> "SubscriptionStats":
        by_status = {
            status.value: counts.get(status.value, 0) for status in SubscriptionStatus
        }

        return cls(
            total=sum(by_status.values()),
            mailable=by_status[SubscriptionStatus.SUBSCRIBED.value],
            pending=by_status[SubscriptionStatus.PENDING.value],
            subscribed=by_status[SubscriptionStatus.SUBSCRIBED.value],
            unsubscribed=by_status[SubscriptionStatus.UNSUBSCRIBED.value],
            bounced=by_status[SubscriptionStatus.BOUNCED.value],
        )
