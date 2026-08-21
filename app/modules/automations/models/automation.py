"""Automation model."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.automations.constants import (
    AUTOMATION_IMAGE_URL_MAX_LENGTH,
    AUTOMATION_SLUG_MAX_LENGTH,
    AUTOMATION_TITLE_MAX_LENGTH,
    AutomationStatus,
)
from app.modules.categories.models.category import Category
from app.modules.users.models.user import User
from app.shared.models.seo import SEOFieldsMixin
from app.shared.utils.dates import utc_now


class Automation(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SEOFieldsMixin
):
    """A publishable automation catalogue entry."""

    title: Mapped[str] = mapped_column(
        String(AUTOMATION_TITLE_MAX_LENGTH), nullable=False
    )
    slug: Mapped[str] = mapped_column(
        String(AUTOMATION_SLUG_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="The automation's address. Fixed once it has been published.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    lists: Mapped[list | None] = mapped_column(
        JSON,
        default=None,
        doc="Free-form bullet content - features, steps, integrations.",
    )

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    image_url: Mapped[str | None] = mapped_column(
        String(AUTOMATION_IMAGE_URL_MAX_LENGTH), default=None
    )
    video_url: Mapped[str | None] = mapped_column(
        String(AUTOMATION_IMAGE_URL_MAX_LENGTH), default=None
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=AutomationStatus.DRAFT.value,
        server_default=AutomationStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="When the automation went live, or is due to. Null while a draft.",
    )

    # -- Audit ----------------------------------------------------------
    # `SET NULL` throughout: removing an account must not remove the entries
    # it wrote.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=[category_id]
    )
    creator: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[created_by]
    )

    __table_args__ = (
        # The listing every reader sees: live entries, newest first.
        Index("ix_automations_status_published_at", "status", "published_at"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_published(self) -> bool:
        return self.status == AutomationStatus.PUBLISHED

    @property
    def is_live(self) -> bool:
        """Whether a reader should be served this automation right now.

        Published and dated in the past. A published entry with a future
        `published_at` is scheduled: it needs no job to go live, because
        every read compares the date against the clock.
        """
        return (
            self.is_published
            and self.published_at is not None
            and self.published_at <= utc_now()
        )

    @property
    def is_scheduled(self) -> bool:
        return self.is_published and not self.is_live

    def __repr__(self) -> str:
        return f"<Automation {self.slug}>"
