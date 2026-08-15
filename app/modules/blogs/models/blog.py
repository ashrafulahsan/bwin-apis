"""Blog post model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.blogs.constants import (
    BLOG_EXCERPT_MAX_LENGTH,
    BLOG_IMAGE_ALT_MAX_LENGTH,
    BLOG_IMAGE_URL_MAX_LENGTH,
    BLOG_SLUG_MAX_LENGTH,
    BLOG_TITLE_MAX_LENGTH,
    BlogStatus,
)
from app.modules.blogs.models.blog_tag import blog_tags
from app.modules.categories.models.category import Category
from app.modules.users.models.user import User
from app.shared.models.seo import SEOFieldsMixin
from app.shared.utils.dates import utc_now


class Blog(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SEOFieldsMixin):
    """One post, filed under a category and carrying any number of tags.

    Both the category and the tags are rows in `categories`: the category
    comes from the `blog_category` taxonomy and the tags from `blog_tag`. The
    column types cannot express that restriction - a foreign key names a
    table, not a subset of it - so the service checks it on every write.
    """

    title: Mapped[str] = mapped_column(String(BLOG_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(BLOG_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="The post's address. Fixed once the post has been published.",
    )
    excerpt: Mapped[str | None] = mapped_column(
        String(BLOG_EXCERPT_MAX_LENGTH),
        default=None,
        doc="Short summary for listings, and the fallback meta description.",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    featured_image_url: Mapped[str | None] = mapped_column(
        String(BLOG_IMAGE_URL_MAX_LENGTH), default=None
    )
    featured_image_alt: Mapped[str | None] = mapped_column(
        String(BLOG_IMAGE_ALT_MAX_LENGTH),
        default=None,
        doc="Alternative text. Required for accessibility wherever an image is.",
    )

    blog_category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`, as in the categories module: retiring a category must
        # not take the posts filed under it.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=BlogStatus.DRAFT.value,
        server_default=BlogStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="When the post went live, or is due to. Null while it is a draft.",
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    reading_minutes: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Estimated from the word count whenever the content changes.",
    )

    # -- People ---------------------------------------------------------
    # `SET NULL` throughout: removing an account must not remove the posts it
    # wrote, and a byline that outlives the account is the normal case.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Whose byline this carries - not necessarily who typed it in.",
    )
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

    # -- Relationships --------------------------------------------------
    # `foreign_keys` is spelled out on every one of these: `blogs` points at
    # `users` three times over, so SQLAlchemy cannot infer which column each
    # relationship travels along.
    category: Mapped[Category] = relationship(
        lazy="selectin", foreign_keys=lambda: [Blog.blog_category_id]
    )
    tags: Mapped[list[Category]] = relationship(
        secondary=blog_tags,
        lazy="selectin",
        order_by=Category.name,
        doc="Categories from the `blog_tag` taxonomy.",
    )
    author: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [Blog.author_id]
    )

    __table_args__ = (
        # The listing every reader sees: live posts, newest first.
        Index("ix_blogs_status_published_at", "status", "published_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_published(self) -> bool:
        return self.status == BlogStatus.PUBLISHED

    @property
    def is_live(self) -> bool:
        """Whether a reader should be served this post right now.

        Published and dated in the past. A published post with a future
        `published_at` is scheduled: it needs no job to go live, because
        every read compares the date against the clock.
        """
        return (
            self.status == BlogStatus.PUBLISHED
            and self.published_at is not None
            and self.published_at <= utc_now()
        )

    @property
    def is_scheduled(self) -> bool:
        return self.is_published and not self.is_live

    def __repr__(self) -> str:
        return f"<Blog {self.slug}>"
