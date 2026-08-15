"""Password reset tokens.

A reset link is a credential that arrives by email or SMS, so it is treated
like one. Only the SHA-256 digest is stored: a database dump then gives up no
working links, and even an administrator reading the table cannot take over an
account with what they find there.

Unlike the JWTs elsewhere in this module, the token itself is opaque random
bytes. There is nothing to encode in it - the row already knows who it belongs
to and when it expires - and a shorter, claim-free string is a better thing to
paste into a URL that will sit in somebody's inbox.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.auth.constants import (
    IP_ADDRESS_MAX_LENGTH,
    TOKEN_FINGERPRINT_LENGTH,
)
from app.shared.utils.dates import utc_now

if TYPE_CHECKING:
    from app.modules.users.models.user import User


class PasswordResetToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One issued reset link."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(TOKEN_FINGERPRINT_LENGTH),
        nullable=False,
        unique=True,
        doc="SHA-256 of the token. The token itself is never stored.",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="Set the moment the link is spent, so it works exactly once.",
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="Set when a newer link supersedes this one.",
    )

    #: Where the request came from. Not used for any decision - it is here so
    #: a user asking "who tried to reset my password?" can be answered.
    requested_ip: Mapped[str | None] = mapped_column(
        String(IP_ADDRESS_MAX_LENGTH), default=None
    )
    #: Which identifier was used to ask. Receiving a link at an address proves
    #: control of it, which is what lets a reset also verify the address.
    requested_via: Mapped[str | None] = mapped_column(
        String(20), default=None, doc="`email` or `phone`."
    )

    user: Mapped["User"] = relationship()

    __table_args__ = (
        # Both the throttle and "invalidate the older links" filter on the
        # user and how recently the row was created.
        Index("ix_password_reset_tokens_user_id_created_at", "user_id", "created_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_invalidated(self) -> bool:
        return self.invalidated_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= utc_now()

    @property
    def is_usable(self) -> bool:
        return not (self.is_used or self.is_invalidated or self.is_expired)

    def spend(self) -> None:
        """Mark the link used. Spending twice keeps the original moment."""
        if self.used_at is None:
            self.used_at = utc_now()

    def __repr__(self) -> str:
        return f"<PasswordResetToken user={self.user_id} usable={self.is_usable}>"
