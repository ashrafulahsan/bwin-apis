"""Category model: one node in a taxonomy's tree."""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.constants import (
    CATEGORY_NAME_MAX_LENGTH,
    CATEGORY_SLUG_MAX_LENGTH,
    CategoryStatus,
)
from app.modules.categories.models.category_type import CategoryType


class Category(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A category, optionally nested under another of the same type.

    The tree is modelled with a self-referencing parent rather than a nested
    set or a path column: taxonomies here are small and shallow, moves are
    rare, and a parent pointer is the one shape that cannot get out of step
    with itself. The service enforces what the column cannot - that a category
    is never its own ancestor, and never crosses into another type.
    """

    name: Mapped[str] = mapped_column(String(CATEGORY_NAME_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(CATEGORY_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique across every taxonomy, so a URL needs no type to resolve.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)

    category_type_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`, so deleting a taxonomy cannot silently take its whole
        # tree with it. The service refuses and says what is in the way.
        ForeignKey("category_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        doc="Null for a top-level category.",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=CategoryStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )

    # -- Audit ----------------------------------------------------------
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

    category_type: Mapped[CategoryType] = relationship(
        back_populates="categories", lazy="selectin"
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent",
        remote_side=None,
        lazy="raise",
        # The parent side owns the foreign key, so the direction has to be
        # spelled out on a self-referencing relationship.
        foreign_keys=lambda: [Category.parent_category_id],
    )
    parent: Mapped["Category | None"] = relationship(
        back_populates="children",
        remote_side=lambda: [Category.id],
        lazy="selectin",
        foreign_keys=lambda: [Category.parent_category_id],
    )

    __table_args__ = (
        # Two categories in one taxonomy must not share a name, but the same
        # name in two different taxonomies is perfectly ordinary - "Design"
        # can be both a course subject and a blog topic.
        UniqueConstraint("category_type_id", "name", name="uq_categories_type_name"),
        # "The children of this category", which is every tree read.
        Index("ix_categories_parent_category_id", "parent_category_id"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == CategoryStatus.ACTIVE

    @property
    def is_root(self) -> bool:
        return self.parent_category_id is None

    def __repr__(self) -> str:
        return f"<Category {self.slug}>"
