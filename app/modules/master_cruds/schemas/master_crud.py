"""Request and response schemas for master CRUD records."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.categories.schemas.category import CategorySummary
from app.modules.master_cruds.constants import (
    MASTER_CRUD_LINK_MAX_LENGTH,
    MASTER_CRUD_TITLE_MAX_LENGTH,
    MASTER_CRUD_VALUE_MAX_LENGTH,
    MasterCrudStatus,
)


class MasterCrudFieldValueInput(BaseModel):
    """One answer, on the way in.

    The value arrives as text whatever the field's type, and the service
    validates it against that type - `"abc"` for a number field is a 400, not
    a stored string that breaks the next reader.
    """

    master_crud_field_id: uuid.UUID
    value: str | None = Field(default=None, max_length=MASTER_CRUD_VALUE_MAX_LENGTH)


class MasterCrudFieldValueRead(BaseModel):
    """One answer, on the way out, carrying enough to render itself."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    master_crud_field_id: uuid.UUID
    field_name: str
    field_type: str
    field_requiredness: bool
    value: str | None

    @classmethod
    def from_model(cls, row: object) -> "MasterCrudFieldValueRead":
        """Flatten the joined field onto the value.

        A client rendering a record should not have to hold the field
        definitions alongside it just to know what each answer was called.
        """
        field = row.field  # type: ignore[attr-defined]

        return cls(
            id=row.id,  # type: ignore[attr-defined]
            master_crud_field_id=row.master_crud_field_id,  # type: ignore[attr-defined]
            field_name=field.field_name,
            field_type=field.field_type,
            field_requiredness=field.field_requiredness,
            value=row.value,  # type: ignore[attr-defined]
        )


class MasterCrudCreate(BaseModel):
    """A new record.

    `field_values` answers the fields defined on `category_id`. Every active,
    required field of that category must appear; a field belonging to another
    category is refused. Omitting `order` puts the record last in its
    category. The slug is derived from the title, so it is not accepted here.
    """

    title: str = Field(min_length=1, max_length=MASTER_CRUD_TITLE_MAX_LENGTH)
    description: str | None = None
    link: str | None = Field(default=None, max_length=MASTER_CRUD_LINK_MAX_LENGTH)
    category_id: uuid.UUID
    order: int | None = Field(
        default=None, ge=1, description="Position in the category. Defaults to last."
    )
    status: MasterCrudStatus = MasterCrudStatus.ACTIVE
    field_values: list[MasterCrudFieldValueInput] = Field(default_factory=list)


class MasterCrudUpdate(BaseModel):
    """Partial update; omitted fields are left alone.

    `field_values` is all-or-nothing: sending it replaces the whole set, which
    is what a form submission means. Omitting it leaves the stored answers
    untouched.
    """

    title: str | None = Field(
        default=None, min_length=1, max_length=MASTER_CRUD_TITLE_MAX_LENGTH
    )
    description: str | None = None
    link: str | None = Field(default=None, max_length=MASTER_CRUD_LINK_MAX_LENGTH)
    category_id: uuid.UUID | None = None
    order: int | None = Field(default=None, ge=1)
    status: MasterCrudStatus | None = None
    field_values: list[MasterCrudFieldValueInput] | None = None


class MasterCrudRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    description: str | None
    link: str | None
    category_id: uuid.UUID
    category: CategorySummary
    order: int
    status: str
    field_values: list[MasterCrudFieldValueRead]
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, record: object) -> "MasterCrudRead":
        """Build the response, flattening each value's field onto it."""
        return cls(
            id=record.id,  # type: ignore[attr-defined]
            title=record.title,  # type: ignore[attr-defined]
            slug=record.slug,  # type: ignore[attr-defined]
            description=record.description,  # type: ignore[attr-defined]
            link=record.link,  # type: ignore[attr-defined]
            category_id=record.category_id,  # type: ignore[attr-defined]
            category=CategorySummary.model_validate(record.category),  # type: ignore[attr-defined]
            order=record.order,  # type: ignore[attr-defined]
            status=record.status,  # type: ignore[attr-defined]
            field_values=[
                MasterCrudFieldValueRead.from_model(value)
                for value in record.field_values  # type: ignore[attr-defined]
            ],
            created_by=record.created_by,  # type: ignore[attr-defined]
            updated_by=record.updated_by,  # type: ignore[attr-defined]
            created_at=record.created_at,  # type: ignore[attr-defined]
            updated_at=record.updated_at,  # type: ignore[attr-defined]
        )


class MasterCrudSummary(BaseModel):
    """Compact form, for lists and for embedding elsewhere."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    link: str | None
    order: int
    status: str
