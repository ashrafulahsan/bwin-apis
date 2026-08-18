"""Master CRUD model: one record filed under a category."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.models.category import Category
from app.modules.master_cruds.constants import (
    MASTER_CRUD_LINK_MAX_LENGTH,
    MASTER_CRUD_SLUG_MAX_LENGTH,
    MASTER_CRUD_TITLE_MAX_LENGTH,
    MasterCrudStatus,
)
from app.modules.master_cruds.models.master_crud_field_value import MasterCrudFieldValue


class MasterCrud(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One record, answering the fields its category defines.

    The fixed columns here are the ones every record has whatever its
    category - a title, an address, a position in a list. Everything specific
    to a kind of record lives in `field_values`, which is why adding a
    question is a row rather than a migration.
    """

    title: Mapped[str] = mapped_column(
        String(MASTER_CRUD_TITLE_MAX_LENGTH), nullable=False
    )
    slug: Mapped[str] = mapped_column(
        String(MASTER_CRUD_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Derived from the title, and unchanged by a rename - it is in links.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    link: Mapped[str | None] = mapped_column(
        String(MASTER_CRUD_LINK_MAX_LENGTH),
        default=None,
        doc="Where the record points: an internal slug or a full URL.",
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`, as everywhere else that points at a category: retiring
        # one must not take the records filed under it.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    order: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Position within the category, ascending. Positive; the service "
        "assigns the next free number when none is given.",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=MasterCrudStatus.ACTIVE.value,
        server_default=MasterCrudStatus.ACTIVE.value,
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

    category: Mapped[Category] = relationship(
        lazy="selectin", foreign_keys=lambda: [MasterCrud.category_id]
    )
    field_values: Mapped[list[MasterCrudFieldValue]] = relationship(
        back_populates="master_crud",
        lazy="selectin",
        # The values are part of the record, not a separate thing that
        # outlives it, so a purge takes them along. Records are soft deleted,
        # so this only fires on a genuine delete.
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # `order` is positive by specification, so the database says so too.
        CheckConstraint('"order" > 0', name="order_positive"),
        # The listing every reader asks for: one category, in order.
        Index("ix_master_cruds_category_id_order", "category_id", "order"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == MasterCrudStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<MasterCrud {self.slug}>"
