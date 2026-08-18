"""Master CRUD field model: one input in a category's form."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.models.category import Category
from app.modules.master_cruds.constants import (
    MASTER_CRUD_FIELD_NAME_MAX_LENGTH,
    FieldType,
    MasterCrudStatus,
)


class MasterCrudField(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One question asked of every record in a category.

    Fields are defined per category rather than per record, which is what
    makes the values comparable: every record filed under "Suppliers" answers
    the same set, so a listing can put them side by side.
    """

    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`: retiring a category must not silently take the form
        # definition - and with it the meaning of every stored value.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    field_name: Mapped[str] = mapped_column(
        String(MASTER_CRUD_FIELD_NAME_MAX_LENGTH),
        nullable=False,
        doc="The label shown on the form, and the key a reader recognises.",
    )
    field_type: Mapped[str] = mapped_column(
        String(20),
        default=FieldType.TEXT.value,
        server_default=FieldType.TEXT.value,
        nullable=False,
        doc="How a value is validated and how the front end renders the input.",
    )
    field_requiredness: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether a record may be saved without answering this.",
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
        lazy="selectin", foreign_keys=lambda: [MasterCrudField.category_id]
    )

    __table_args__ = (
        # Two fields in one category must not share a name: the name is what a
        # reader matches a value to, and two "Phone number" columns make every
        # export ambiguous. The same name in another category is ordinary.
        UniqueConstraint(
            "category_id", "field_name", name="uq_master_crud_fields_category_name"
        ),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == MasterCrudStatus.ACTIVE

    @property
    def is_required(self) -> bool:
        return self.field_requiredness

    def __repr__(self) -> str:
        return f"<MasterCrudField {self.field_name}>"
