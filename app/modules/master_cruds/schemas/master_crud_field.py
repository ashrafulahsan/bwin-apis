"""Request and response schemas for master CRUD fields."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.categories.schemas.category import CategorySummary
from app.modules.master_cruds.constants import (
    MASTER_CRUD_FIELD_NAME_MAX_LENGTH,
    FieldType,
    MasterCrudStatus,
)


class MasterCrudFieldCreate(BaseModel):
    """A new field on a category's form.

    `field_requiredness` defaults to false: a question added to a form that
    records already exist under should not make every one of them invalid
    unless someone asks for that.
    """

    category_id: uuid.UUID
    field_name: str = Field(min_length=1, max_length=MASTER_CRUD_FIELD_NAME_MAX_LENGTH)
    field_type: FieldType = FieldType.TEXT
    field_requiredness: bool = False
    status: MasterCrudStatus = MasterCrudStatus.ACTIVE


class MasterCrudFieldUpdate(BaseModel):
    """Partial update; omitted fields are left alone."""

    category_id: uuid.UUID | None = None
    field_name: str | None = Field(
        default=None, min_length=1, max_length=MASTER_CRUD_FIELD_NAME_MAX_LENGTH
    )
    field_type: FieldType | None = None
    field_requiredness: bool | None = None
    status: MasterCrudStatus | None = None


class MasterCrudFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    category: CategorySummary
    field_name: str
    field_type: str
    field_requiredness: bool
    status: str
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MasterCrudFieldSummary(BaseModel):
    """Compact form - what a client needs to render one input."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_name: str
    field_type: str
    field_requiredness: bool
    status: str
