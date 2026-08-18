"""Request and response schemas for pages."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field

from app.modules.pages.constants import (
    PAGE_DESCRIPTION_MAX_LENGTH,
    PAGE_IMAGE_ALT_MAX_LENGTH,
    PAGE_IMAGE_URL_MAX_LENGTH,
    PAGE_SLUG_MAX_LENGTH,
    PAGE_TITLE_MAX_LENGTH,
)
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead

if TYPE_CHECKING:
    from app.modules.pages.models.page import Page


class PageWriteBase(BaseModel):
    """Fields shared by create and update, with their limits in one place."""

    description: str | None = Field(
        default=None,
        max_length=PAGE_DESCRIPTION_MAX_LENGTH,
        description="Short summary for listings, and the fallback meta description.",
    )
    thumbnail_image: str | None = Field(
        default=None, max_length=PAGE_IMAGE_URL_MAX_LENGTH
    )
    thumbnail_image_alt: str | None = Field(
        default=None,
        max_length=PAGE_IMAGE_ALT_MAX_LENGTH,
        description="Alternative text for the cover image.",
    )
    is_featured: bool | None = Field(
        default=None, description="Pin this page to the top of a listing."
    )
    seo: SEOMetadata | None = Field(
        default=None,
        description=(
            "Search metadata. Anything omitted is derived from the page - the "
            "meta title from the title, the description from the summary - so "
            "a page is never served without it. `meta_keywords` is the field "
            "a `meta_tag` box writes to."
        ),
    )


class PageCreate(PageWriteBase):
    """A new page.

    Always created as a draft: publishing is a separate call, so that it can
    require a separate permission. `slug` may be supplied when an editor wants
    a particular URL, otherwise it is derived from the title.
    """

    title: str = Field(min_length=1, max_length=PAGE_TITLE_MAX_LENGTH)
    content: str = Field(min_length=1)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=PAGE_SLUG_MAX_LENGTH,
        description="Derived from the title when omitted.",
    )


class PageUpdate(PageWriteBase):
    """Partial update; omitted fields are left alone.

    `status` is deliberately absent. Publishing runs through its own endpoint,
    so it can require its own permission and so the publication date is set by
    the transition rather than typed in by hand.
    """

    title: str | None = Field(
        default=None, min_length=1, max_length=PAGE_TITLE_MAX_LENGTH
    )
    content: str | None = Field(default=None, min_length=1)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=PAGE_SLUG_MAX_LENGTH,
        description="Only while the page is still a draft.",
    )


class PagePublish(BaseModel):
    """Take a page live, optionally at a chosen moment."""

    published_at: datetime | None = Field(
        default=None,
        description=(
            "When the page should be considered live. Defaults to now; a "
            "future time schedules it, and no background job is needed to "
            "flip it over. A page that has been live before keeps its "
            "original date."
        ),
    )


class PageSummary(BaseModel):
    """A page as it appears in a listing: everything except the body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    description: str | None
    thumbnail_image: str | None
    thumbnail_image_alt: str | None
    status: str
    is_featured: bool
    is_live: bool
    is_scheduled: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PageRead(PageSummary):
    """A single page in full, with its search metadata resolved."""

    content: str
    seo: SEOMetadataRead
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    @classmethod
    def from_model(cls, page: "Page") -> Self:
        """Build the response, resolving the metadata it serves.

        `model_validate` cannot do this alone: `seo` is assembled from eight
        columns plus the page's own title and summary, so that a client
        rendering `<head>` never has to know the fallback order - and two
        clients cannot disagree about it.
        """
        listed = PageSummary.model_validate(page)

        return cls(
            **listed.model_dump(),
            content=page.content,
            created_by=page.created_by,
            updated_by=page.updated_by,
            seo=SEOMetadataRead.resolve(
                page,
                title=page.title,
                summary=page.description,
                image_url=page.thumbnail_image,
            ),
        )
