"""User model."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_LANGUAGE
from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.roles.models.role import Role
from app.modules.users.constants import (
    AVATAR_URL_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    PROVIDER_USER_ID_MAX_LENGTH,
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

    # -- Social sign-in -------------------------------------------------
    # `user_identities` remains the source of truth: it holds the uniqueness
    # constraints and can carry several providers per account. These columns
    # are a denormalized copy for the common single-provider case, so a list
    # screen can filter and sort on them without a join. Written in exactly
    # one place - `UserRepository._sync_social_columns`, which recomputes them
    # from the identity rows - so the two cannot drift apart.
    google_id: Mapped[str | None] = mapped_column(
        String(PROVIDER_USER_ID_MAX_LENGTH), unique=True, index=True, default=None
    )
    facebook_id: Mapped[str | None] = mapped_column(
        String(PROVIDER_USER_ID_MAX_LENGTH), unique=True, index=True, default=None
    )
    social_provider: Mapped[str | None] = mapped_column(
        String(30),
        default=None,
        doc="The provider this account first arrived through, if any.",
    )
    is_social_login: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        # A server default too, not just a Python one: this column is NOT
        # NULL, and anything writing a row without going through the ORM - a
        # migration, a repair script - would otherwise fail on it.
        server_default=false(),
        nullable=False,
        index=True,
        doc="Whether any social account is linked.",
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
    tokens_valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc=(
            "Access tokens issued before this are refused. Set when the "
            "password changes, which is the one thing an access token cannot "
            "otherwise be told about."
        ),
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
