"""Linked external identities (Google, Facebook).

A separate table rather than columns on `users`, so one account can carry a
password plus several social logins, and a new provider needs no migration of
the users table.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.users.constants import (
    EMAIL_MAX_LENGTH,
    PROVIDER_USER_ID_MAX_LENGTH,
)

if TYPE_CHECKING:
    from app.modules.users.models.user import User


class UserIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One external account linked to a platform user."""

    __tablename__ = "user_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, doc="`google` or `facebook`."
    )
    provider_user_id: Mapped[str] = mapped_column(
        String(PROVIDER_USER_ID_MAX_LENGTH),
        nullable=False,
        doc="The provider's own stable identifier for the account.",
    )
    email: Mapped[str | None] = mapped_column(
        String(EMAIL_MAX_LENGTH),
        default=None,
        doc="Email the provider reported, kept for support and auditing.",
    )

    user: Mapped["User"] = relationship(back_populates="identities")

    __table_args__ = (
        # The provider's id is the identity. Two platform accounts must never
        # claim the same Google account.
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_user_identities_provider_id"
        ),
        # One link per provider per user.
        UniqueConstraint(
            "user_id", "provider", name="uq_user_identities_user_provider"
        ),
    )

    def __repr__(self) -> str:
        return f"<UserIdentity {self.provider}:{self.provider_user_id}>"
