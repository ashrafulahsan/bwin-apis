"""Request and response schemas for category types and categories."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.categories.constants import (
    CATEGORY_NAME_MAX_LENGTH,
    CategoryStatus,
)

# -- Category types -----------------------------------------------------


class CategoryTypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    description: str | None = None
    status: CategoryStatus = CategoryStatus.ACTIVE


class CategoryTypeCreate(CategoryTypeBase):
    """The slug is derived from the name, so it is not accepted here."""


class CategoryTypeUpdate(BaseModel):
    """Partial update; omitted fields are left alone."""

    name: str | None = Field(
        default=None, min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH
    )
    description: str | None = None
    status: CategoryStatus | None = None


class CategoryTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: str
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CategoryTypeSummary(BaseModel):
    """Compact form, for embedding in a category."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: str


# -- Categories ---------------------------------------------------------


class CategoryCreate(BaseModel):
    """A new category.

    `parent_category_id` is optional; omit it for a top-level category. A
    parent must belong to the same type, so a taxonomy cannot grow a branch
    out of another one.
    """

    name: str = Field(min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    description: str | None = None
    category_type_id: uuid.UUID
    parent_category_id: uuid.UUID | None = None
    status: CategoryStatus = CategoryStatus.ACTIVE


class CategoryUpdate(BaseModel):
    """Partial update.

    Sending `parent_category_id: null` moves the category to the top level;
    omitting the field leaves the parent where it is. Pydantic's
    `exclude_unset` is what separates the two, so a client can express both.
    """

    name: str | None = Field(
        default=None, min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH
    )
    description: str | None = None
    category_type_id: uuid.UUID | None = None
    parent_category_id: uuid.UUID | None = None
    status: CategoryStatus | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    category_type_id: uuid.UUID
    category_type: CategoryTypeSummary
    parent_category_id: uuid.UUID | None
    status: str
    is_root: bool
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CategorySummary(BaseModel):
    """Compact form, for lists and for embedding in other modules."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: str


class CategoryNode(BaseModel):
    """One category with its descendants, for rendering a menu in one call."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: str
    parent_category_id: uuid.UUID | None
    children: list["CategoryNode"] = Field(default_factory=list)


class CategoryMove(BaseModel):
    """Re-parent a category on its own, without touching anything else."""

    parent_category_id: uuid.UUID | None = Field(
        default=None, description="Null moves the category to the top level."
    )


CategoryNode.model_rebuild()
