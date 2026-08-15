"""Category type model: one named taxonomy."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.constants import (
    CATEGORY_NAME_MAX_LENGTH,
    CATEGORY_SLUG_MAX_LENGTH,
    CategoryStatus,
)

if TYPE_CHECKING:
    from app.modules.categories.models.category import Category


class CategoryType(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A taxonomy that categories belong to, such as "Course Subjects"."""

    name: Mapped[str] = mapped_column(
        String(CATEGORY_NAME_MAX_LENGTH),
        unique=True,
        nullable=False,
        doc="Display name, editable by administrators.",
    )
    slug: Mapped[str] = mapped_column(
        String(CATEGORY_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable identifier used in URLs and in code.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[str] = mapped_column(
        String(20),
        default=CategoryStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )

    # -- Audit ----------------------------------------------------------
    # `SET NULL` rather than `CASCADE`: deleting the administrator who created
    # a taxonomy must not delete the taxonomy along with them.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    categories: Mapped[list["Category"]] = relationship(
        back_populates="category_type",
        # Not eager: a taxonomy can hold hundreds of categories, and most
        # reads of a type do not want them. The endpoints that do ask for the
        # tree explicitly.
        lazy="raise",
    )

    @property
    def is_active(self) -> bool:
        return self.status == CategoryStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<CategoryType {self.slug}>"
