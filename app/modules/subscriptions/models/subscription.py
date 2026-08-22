"""Newsletter subscription model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.subscriptions.constants import (
    SUBSCRIPTION_EMAIL_MAX_LENGTH,
    SUBSCRIPTION_IP_ADDRESS_MAX_LENGTH,
    SUBSCRIPTION_NAME_MAX_LENGTH,
    SUBSCRIPTION_REASON_MAX_LENGTH,
    SUBSCRIPTION_SOURCE_MAX_LENGTH,
    TOKEN_FINGERPRINT_LENGTH,
    SubscriptionStatus,
)
from app.shared.utils.dates import utc_now


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One address that has asked to hear from the platform.

    The row outlives the relationship on purpose. Someone who unsubscribes
    keeps their row, set to `UNSUBSCRIBED`: throwing it away would let the
    next import put the address straight back on the list, which is exactly
    what the person asked not to happen.

    Only the confirmation token touches this table, and only as a SHA-256
    digest: it is short-lived and spent once, so a link left in an old inbox
    does not still work a year later. The unsubscribe token is not here at
    all - it is derived from the row's id on demand, for the reasons set out
    in `app.modules.subscriptions.tokens`.
    """

    email: Mapped[str] = mapped_column(
        String(SUBSCRIPTION_EMAIL_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Normalized to lowercase, so one address cannot be listed twice.",
    )
    name: Mapped[str | None] = mapped_column(
        String(SUBSCRIPTION_NAME_MAX_LENGTH),
        default=None,
        doc="Optional. A signup box that demands a name collects fewer.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=SubscriptionStatus.PENDING.value,
        server_default=SubscriptionStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    source: Mapped[str | None] = mapped_column(
        String(SUBSCRIPTION_SOURCE_MAX_LENGTH),
        default=None,
        index=True,
        doc="Where the signup came from: `website`, `admin`, a campaign name.",
    )

    # -- Confirmation ---------------------------------------------------

    confirmation_token_hash: Mapped[str | None] = mapped_column(
        String(TOKEN_FINGERPRINT_LENGTH),
        unique=True,
        default=None,
        doc="SHA-256 of the confirmation token. Cleared once it is spent.",
    )
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="When the last link went out. The resend cooldown reads this.",
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="When the address proved it wanted this. The record of consent.",
    )

    # -- Leaving --------------------------------------------------------

    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    unsubscribe_reason: Mapped[str | None] = mapped_column(
        String(SUBSCRIPTION_REASON_MAX_LENGTH),
        default=None,
        doc="Optional, and offered rather than required.",
    )

    # -- Consent record -------------------------------------------------
    # Where the signup came from, kept so "we never asked for this" can be
    # answered with something better than an assurance.
    signup_ip: Mapped[str | None] = mapped_column(
        String(SUBSCRIPTION_IP_ADDRESS_MAX_LENGTH), default=None
    )

    # -- Audit ----------------------------------------------------------
    # `SET NULL`: removing a staff account must not remove the subscribers
    # they added. Both stay null for a signup from the public form, which has
    # no account behind it.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    __table_args__ = (
        # The query every send starts with: who is on the list, and where did
        # they come from.
        Index("ix_subscriptions_status_created_at", "status", "created_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_confirmed(self) -> bool:
        return self.status == SubscriptionStatus.SUBSCRIBED

    @property
    def is_pending(self) -> bool:
        return self.status == SubscriptionStatus.PENDING

    @property
    def is_mailable(self) -> bool:
        """Whether a campaign may be sent to this address right now.

        The one question a send asks. `PENDING` is deliberately excluded: an
        address that has not confirmed is not on the list, whatever it looks
        like in a listing.
        """
        return self.status == SubscriptionStatus.SUBSCRIBED

    @property
    def confirmation_expired(self) -> bool:
        return (
            self.confirmation_expires_at is not None
            and self.confirmation_expires_at <= utc_now()
        )

    def __repr__(self) -> str:
        return f"<Subscription {self.email} {self.status}>"
