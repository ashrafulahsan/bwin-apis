"""User model."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_LANGUAGE
from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.roles.models.role import Role
from app.modules.users.constants import (
    AVATAR_URL_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    UserStatus,
)
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A platform account.

    Either `email` or `phone` identifies the account, and both can sign in.
    Both are nullable because a social sign-up may supply only one of them -
    a `CHECK` constraint guarantees at least one is present, so an account can
    never exist with no way to reach or identify it.

    `password_hash` is nullable too: an account created through Google has no
    password until the user sets one.
    """

    email: Mapped[str | None] = mapped_column(
        String(EMAIL_MAX_LENGTH),
        unique=True,
        index=True,
        default=None,
        doc="Stored lowercase, so lookups are case-insensitive.",
    )
    phone: Mapped[str | None] = mapped_column(
        String(PHONE_MAX_LENGTH),
        unique=True,
        index=True,
        default=None,
        doc="Stored in E.164, e.g. `+8801712345678`.",
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255), default=None, doc="Null for accounts that only use social login."
    )

    first_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(NAME_MAX_LENGTH), default=None)
    avatar_url: Mapped[str | None] = mapped_column(
        String(AVATAR_URL_MAX_LENGTH), default=None
    )
    bio: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[str] = mapped_column(
        String(20), default=UserStatus.PENDING, nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(
        String(5), default=DEFAULT_LANGUAGE.value, nullable=False
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        order_by=Role.level.desc(),
        # Eager: a lazy load outside the original await raises MissingGreenlet
        # under asyncio, and authorization needs the roles on every request.
        lazy="selectin",
    )
    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="user_has_an_identifier",
        ),
    )

    # -- Derived state --------------------------------------------------

    @property
    def full_name(self) -> str:
        return (
            f"{self.first_name} {self.last_name}".strip()
            if self.last_name
            else self.first_name
        )

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def can_sign_in(self) -> bool:
        """Suspended and deactivated accounts are refused at the door."""
        return self.status in {UserStatus.ACTIVE, UserStatus.PENDING}

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    @property
    def role_slugs(self) -> set[str]:
        return {role.slug for role in self.roles}

    @property
    def permission_codes(self) -> set[str]:
        """Union of every permission granted by every role held."""
        return {
            permission.code for role in self.roles for permission in role.permissions
        }

    @property
    def highest_level(self) -> int:
        """Level of the most privileged role held; 0 when the user has none."""
        return max((role.level for role in self.roles), default=0)

    def has_role(self, slug: str) -> bool:
        return slug in self.role_slugs

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes

    def linked_providers(self) -> set[str]:
        return {identity.provider for identity in self.identities}

    def __repr__(self) -> str:
        return f"<User {self.email or self.phone}>"
