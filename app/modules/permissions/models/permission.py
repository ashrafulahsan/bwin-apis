"""Permission model."""

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.permissions.constants import (
    PERMISSION_CODE_MAX_LENGTH,
    PERMISSION_NAME_MAX_LENGTH,
    PERMISSION_PART_MAX_LENGTH,
)


class Permission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single grantable capability, identified by `resource.action`."""

    code: Mapped[str] = mapped_column(
        String(PERMISSION_CODE_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable identifier used in code, e.g. `user.view`.",
    )
    resource: Mapped[str] = mapped_column(
        String(PERMISSION_PART_MAX_LENGTH),
        index=True,
        nullable=False,
        doc="Left half of the code, stored separately for grouping.",
    )
    action: Mapped[str] = mapped_column(
        String(PERMISSION_PART_MAX_LENGTH), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(PERMISSION_NAME_MAX_LENGTH),
        nullable=False,
        doc="Human readable label, e.g. `View users`.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Seeded with the platform. Cannot be deleted.",
    )

    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permissions_resource_action"),
    )

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"
