"""Page model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.pages.constants import (
    PAGE_DESCRIPTION_MAX_LENGTH,
    PAGE_IMAGE_ALT_MAX_LENGTH,
    PAGE_IMAGE_URL_MAX_LENGTH,
    PAGE_SLUG_MAX_LENGTH,
    PAGE_TITLE_MAX_LENGTH,
    PageStatus,
)
from app.shared.models.seo import SEOFieldsMixin
from app.shared.utils.dates import utc_now


class Page(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SEOFieldsMixin):
    """One page of standalone content, addressed by its slug.

    The `meta_*` and `og_*` columns come from `SEOFieldsMixin`, shared with
    blog posts and with the course pages still to come. Sharing them is the
    point: the three cannot drift apart, and the fallback cascade that fills
    an author's blanks is written once, in `app.shared.schemas.seo`.
    """

    title: Mapped[str] = mapped_column(String(PAGE_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(PAGE_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="The page's address. Fixed once the page has been published.",
    )
    description: Mapped[str | None] = mapped_column(
        String(PAGE_DESCRIPTION_MAX_LENGTH),
        default=None,
        doc="Short summary for listings, and the fallback meta description.",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    thumbnail_image: Mapped[str | None] = mapped_column(
        String(PAGE_IMAGE_URL_MAX_LENGTH),
        default=None,
        doc="Cover image: a path or a full URL.",
    )
    thumbnail_image_alt: Mapped[str | None] = mapped_column(
        String(PAGE_IMAGE_ALT_MAX_LENGTH),
        default=None,
        doc="Alternative text. Required for accessibility wherever an image is.",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=PageStatus.DRAFT.value,
        server_default=PageStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="When the page went live, or is due to. Null while it is a draft.",
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # -- Audit ----------------------------------------------------------
    # `SET NULL` throughout: removing an account must not remove the pages it
    # wrote.
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

    __table_args__ = (
        # The listing every reader sees: live pages, newest first.
        Index("ix_pages_status_published_at", "status", "published_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_published(self) -> bool:
        return self.status == PageStatus.PUBLISHED

    @property
    def is_live(self) -> bool:
        """Whether a reader should be served this page right now.

        Published and dated in the past. A published page with a future
        `published_at` is scheduled: it needs no job to go live, because every
        read compares the date against the clock.
        """
        return (
            self.status == PageStatus.PUBLISHED
            and self.published_at is not None
            and self.published_at <= utc_now()
        )

    @property
    def is_scheduled(self) -> bool:
        return self.is_published and not self.is_live

    def __repr__(self) -> str:
        return f"<Page {self.slug}>"
