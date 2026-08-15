"""Persisted refresh tokens - the record that makes logout mean something.

JWTs are self-contained, so a signed token stays valid until it expires no
matter what the server thinks. Keeping a row per refresh token is what lets a
session actually be ended: refreshing checks this table, and logout marks the
row revoked.

Only the SHA-256 digest of the token is stored. The row identifies a session
and records when and from where it started; it never holds anything that could
be replayed.
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
    USER_AGENT_MAX_LENGTH,
    RevocationReason,
)
from app.shared.utils.dates import utc_now

if TYPE_CHECKING:
    from app.modules.users.models.user import User


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One issued refresh token, and therefore one signed-in session."""

    __tablename__ = "refresh_tokens"

    # No index of its own: the composite below leads with this column, and
    # PostgreSQL will use a leading-column prefix, so a second index on
    # `user_id` alone would cost writes and buy nothing.
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
    #: The `jti` claim, kept alongside the digest purely so a session can be
    #: traced through the logs without holding anything replayable.
    token_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(30), default=None)

    user_agent: Mapped[str | None] = mapped_column(
        String(USER_AGENT_MAX_LENGTH),
        default=None,
        doc="Recorded so a user can recognise their own sessions.",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(IP_ADDRESS_MAX_LENGTH), default=None
    )

    user: Mapped["User"] = relationship()

    __table_args__ = (
        # Every refresh and every logout-all filters on this pair. Revoked and
        # expired rows are kept for auditing, so the index earns its keep as
        # the table grows.
        Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= utc_now()

    @property
    def is_active(self) -> bool:
        """Usable right now: issued, not revoked, not past its lifetime."""
        return not self.is_revoked and not self.is_expired

    def revoke(self, reason: RevocationReason) -> None:
        """Mark the session ended. Revoking twice keeps the original moment."""
        if self.is_revoked:
            return

        self.revoked_at = utc_now()
        self.revoked_reason = reason.value

    def __repr__(self) -> str:
        state = "revoked" if self.is_revoked else "active"
        return f"<RefreshToken {self.token_id} {state}>"
