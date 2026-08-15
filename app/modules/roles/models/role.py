"""Role model."""

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.roles.constants import (
    MAX_ROLE_LEVEL,
    MIN_ROLE_LEVEL,
    ROLE_NAME_MAX_LENGTH,
    ROLE_SLUG_MAX_LENGTH,
)


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A named set of privileges a user can be granted."""

    name: Mapped[str] = mapped_column(
        String(ROLE_NAME_MAX_LENGTH),
        unique=True,
        nullable=False,
        doc="Display name, editable by administrators.",
    )
    slug: Mapped[str] = mapped_column(
        String(ROLE_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable identifier used in code. Never changes once created.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    level: Mapped[int] = mapped_column(
        Integer,
        default=MIN_ROLE_LEVEL,
        nullable=False,
        doc="Privilege ordering; higher outranks lower.",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Seeded with the platform. Cannot be deleted.",
    )

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        order_by=Permission.code,
        # Eager by design: under asyncio a lazy load outside the original
        # await raises MissingGreenlet, and a role's permission set is small.
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            f"level >= {MIN_ROLE_LEVEL} AND level <= {MAX_ROLE_LEVEL}",
            name="role_level_range",
        ),
    )

    @property
    def permission_codes(self) -> set[str]:
        return {permission.code for permission in self.permissions}

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes

    def outranks(self, other: "Role") -> bool:
        """Whether this role sits strictly above `other`."""
        return self.level > other.level

    def __repr__(self) -> str:
        return f"<Role {self.slug} level={self.level}>"
