"""Request and response schemas for blog posts."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.blogs.constants import (
    BLOG_EXCERPT_MAX_LENGTH,
    BLOG_IMAGE_ALT_MAX_LENGTH,
    BLOG_IMAGE_URL_MAX_LENGTH,
    BLOG_SLUG_MAX_LENGTH,
    BLOG_TITLE_MAX_LENGTH,
    MAX_TAGS_PER_BLOG,
)
from app.modules.categories.schemas.category import CategorySummary
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead

if TYPE_CHECKING:
    from app.modules.blogs.models.blog import Blog


class BlogAuthor(BaseModel):
    """The byline: as much of the account as a reader needs."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    avatar: str | None = None


def _dedupe(values: list[uuid.UUID]) -> list[uuid.UUID]:
    """Drop repeated tags, keeping the order they were sent in.

    Sending the same tag twice is a client bug, not something to fail a
    request over - the unique constraint would reject the second row anyway,
    as an integrity error nobody can act on.
    """
    return list(dict.fromkeys(values))


class BlogWriteBase(BaseModel):
    """Fields shared by create and update, with their limits in one place."""

    excerpt: str | None = Field(default=None, max_length=BLOG_EXCERPT_MAX_LENGTH)
    featured_image_url: str | None = Field(
        default=None, max_length=BLOG_IMAGE_URL_MAX_LENGTH
    )
    featured_image_alt: str | None = Field(
        default=None,
        max_length=BLOG_IMAGE_ALT_MAX_LENGTH,
        description="Alternative text for the cover image.",
    )
    is_featured: bool | None = Field(
        default=None, description="Pin this post to the top of a listing."
    )
    author_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Whose byline the post carries. Defaults to the account creating "
            "it, which is not always the writer."
        ),
    )
    seo: SEOMetadata | None = Field(
        default=None,
        description=(
            "Search metadata. Anything omitted is derived from the post - the "
            "meta title from the title, the description from the excerpt - so "
            "a post is never served without it."
        ),
    )


class BlogCreate(BlogWriteBase):
    """A new post.

    Always created as a draft: publishing is a separate call, so that it can
    require a separate permission. `slug` may be supplied when an editor wants
    a particular URL, otherwise it is derived from the title.
    """

    title: str = Field(min_length=1, max_length=BLOG_TITLE_MAX_LENGTH)
    content: str = Field(min_length=1)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=BLOG_SLUG_MAX_LENGTH,
        description="Derived from the title when omitted.",
    )
    blog_category_id: uuid.UUID = Field(
        description="A category from the `blog_category` taxonomy."
    )
    tag_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_TAGS_PER_BLOG,
        description="Categories from the `blog_tag` taxonomy.",
    )

    @field_validator("tag_ids")
    @classmethod
    def _unique_tags(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe(values)


class BlogUpdate(BlogWriteBase):
    """Partial update; omitted fields are left alone.

    Sending `tag_ids` replaces the whole set - which is what an editor's tag
    box does when it is saved. Omitting it leaves the tags untouched.

    `status` is deliberately absent. Publishing runs through its own endpoint,
    so it can require its own permission and so the publication date is set by
    the transition rather than typed in by hand.
    """

    title: str | None = Field(
        default=None, min_length=1, max_length=BLOG_TITLE_MAX_LENGTH
    )
    content: str | None = Field(default=None, min_length=1)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=BLOG_SLUG_MAX_LENGTH,
        description="Only while the post is still a draft.",
    )
    blog_category_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_TAGS_PER_BLOG)

    @field_validator("tag_ids")
    @classmethod
    def _unique_tags(cls, values: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        return _dedupe(values) if values is not None else None


class BlogPublish(BaseModel):
    """Take a post live, optionally at a chosen moment."""

    published_at: datetime | None = Field(
        default=None,
        description=(
            "When the post should be considered live. Defaults to now; a "
            "future time schedules it, and no background job is needed to "
            "flip it over. A post that has been live before keeps its "
            "original date."
        ),
    )


class BlogSummary(BaseModel):
    """A post as it appears in a listing: everything except the body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    excerpt: str | None
    featured_image_url: str | None
    featured_image_alt: str | None
    status: str
    is_featured: bool
    is_live: bool
    is_scheduled: bool
    reading_minutes: int
    published_at: datetime | None
    category: CategorySummary
    tags: list[CategorySummary]
    author: BlogAuthor | None
    created_at: datetime
    updated_at: datetime


class BlogRead(BlogSummary):
    """A single post in full, with its search metadata resolved."""

    content: str
    blog_category_id: uuid.UUID
    author_id: uuid.UUID | None
    seo: SEOMetadataRead
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    @classmethod
    def from_model(cls, blog: "Blog") -> Self:
        """Build the response, resolving the metadata it serves.

        `model_validate` cannot do this alone: `seo` is assembled from eight
        columns plus the post's own title and excerpt, so that a client
        rendering `<head>` never has to know the fallback order - and two
        clients cannot disagree about it.
        """
        listed = BlogSummary.model_validate(blog)

        return cls(
            **listed.model_dump(),
            content=blog.content,
            blog_category_id=blog.blog_category_id,
            author_id=blog.author_id,
            created_by=blog.created_by,
            updated_by=blog.updated_by,
            seo=SEOMetadataRead.resolve(
                blog,
                title=blog.title,
                summary=blog.excerpt,
                image_url=blog.featured_image_url,
            ),
        )
