"""Master CRUD field value: one record's answer to one field.

A table rather than a JSON column on the record. The values are queried,
filtered and exported per field, and a JSON blob makes every one of those a
scan with no constraint to lean on - nothing would stop a value naming a field
from another category, or the same field twice.

The value itself is stored as text whatever the field's type. A single column
cannot be four types at once, and the alternative - a column per type, three
of them null on every row - is worse to read and worse to query. The service
validates and normalizes on the way in, so what is stored is always parseable
as the type the field declares.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.master_cruds.models.master_crud_field import MasterCrudField

if TYPE_CHECKING:
    from app.modules.master_cruds.models.master_crud import MasterCrud


class MasterCrudFieldValue(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """What one record answered for one field.

    Not soft deleted: a value has no life of its own. It goes when the record
    is purged, and is replaced in place when the record is edited.
    """

    master_crud_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `CASCADE`: these rows describe the record and mean nothing without
        # it. Records are soft deleted, so this only fires on a purge.
        ForeignKey("master_cruds.id", ondelete="CASCADE"),
        nullable=False,
    )
    master_crud_field_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`: a field that records have answered cannot be dropped out
        # from under them - the values would be left saying nothing. The
        # service refuses first and says how many are in the way.
        ForeignKey("master_crud_fields.id", ondelete="RESTRICT"),
        nullable=False,
        # "Which records answered this field", the reverse of the unique
        # index below - and what the delete guard counts.
        index=True,
    )

    value: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        doc="Normalized to the field's type on the way in. Null for a blank "
        "answer to an optional field.",
    )

    master_crud: Mapped["MasterCrud"] = relationship(
        back_populates="field_values",
        foreign_keys=lambda: [MasterCrudFieldValue.master_crud_id],
    )
    field: Mapped[MasterCrudField] = relationship(
        lazy="selectin",
        foreign_keys=lambda: [MasterCrudFieldValue.master_crud_field_id],
    )

    __table_args__ = (
        # One answer per field per record. Without this nothing stops the same
        # field being answered twice, and a reader has no way to choose.
        UniqueConstraint(
            "master_crud_id",
            "master_crud_field_id",
            name="uq_master_crud_field_values_record_field",
        ),
    )

    def __repr__(self) -> str:
        return f"<MasterCrudFieldValue field={self.master_crud_field_id}>"
