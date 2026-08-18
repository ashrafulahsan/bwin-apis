"""Request and response schemas for menu items."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.categories.schemas.category import CategorySummary
from app.modules.menus.constants import (
    MENU_ICON_MAX_LENGTH,
    MENU_IMAGE_MAX_LENGTH,
    MENU_LINK_MAX_LENGTH,
    MENU_TITLE_MAX_LENGTH,
)


class MenuCreate(BaseModel):
    """A new menu item.

    `parent_id` is optional; omit it for a top-level item. A parent must sit
    in the same menu category, so one navigation cannot grow a branch out of
    another. Omitting `order` puts the item last among its siblings.
    """

    title: str = Field(min_length=1, max_length=MENU_TITLE_MAX_LENGTH)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=MENU_ICON_MAX_LENGTH)
    image: str | None = Field(default=None, max_length=MENU_IMAGE_MAX_LENGTH)
    link: str | None = Field(default=None, max_length=MENU_LINK_MAX_LENGTH)
    parent_id: uuid.UUID | None = None
    menu_category_id: uuid.UUID
    order: int | None = Field(
        default=None, ge=1, description="Position among siblings. Defaults to last."
    )


class MenuUpdate(BaseModel):
    """Partial update; omitted fields are left alone.

    Sending `parent_id: null` moves the item to the top level, while omitting
    the field leaves the parent where it is. Pydantic's `exclude_unset` is
    what separates the two, so a client can express both.
    """

    title: str | None = Field(
        default=None, min_length=1, max_length=MENU_TITLE_MAX_LENGTH
    )
    description: str | None = None
    icon: str | None = Field(default=None, max_length=MENU_ICON_MAX_LENGTH)
    image: str | None = Field(default=None, max_length=MENU_IMAGE_MAX_LENGTH)
    link: str | None = Field(default=None, max_length=MENU_LINK_MAX_LENGTH)
    parent_id: uuid.UUID | None = None
    menu_category_id: uuid.UUID | None = None
    order: int | None = Field(default=None, ge=1)


class MenuRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    icon: str | None
    image: str | None
    link: str | None
    parent_id: uuid.UUID | None
    menu_category_id: uuid.UUID
    menu_category: CategorySummary
    order: int
    is_root: bool
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MenuSummary(BaseModel):
    """Compact form, for lists and for embedding elsewhere."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    icon: str | None
    link: str | None
    order: int


class MenuNode(BaseModel):
    """One item with its descendants, for rendering a navigation in one call."""

    id: uuid.UUID
    title: str
    description: str | None
    icon: str | None
    image: str | None
    link: str | None
    parent_id: uuid.UUID | None
    order: int
    children: list["MenuNode"] = Field(default_factory=list)


class MenuMove(BaseModel):
    """Re-parent an item, and optionally place it, without touching the rest."""

    parent_id: uuid.UUID | None = Field(
        default=None, description="Null moves the item to the top level."
    )
    order: int | None = Field(
        default=None, ge=1, description="Position among its new siblings."
    )


MenuNode.model_rebuild()
