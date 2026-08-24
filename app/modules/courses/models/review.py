"""Review model: a learner's rating and written feedback on a course."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.courses.constants import (
    REVIEW_EMAIL_MAX_LENGTH,
    REVIEW_MAX_RATING,
    REVIEW_MIN_RATING,
    REVIEW_NAME_MAX_LENGTH,
    REVIEW_TITLE_MAX_LENGTH,
    ReviewSource,
    ReviewStatus,
)
from app.modules.users.models.user import User


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One rating and comment left against a course.

    `user_id` is nullable and the reviewer's own name and photo are stored
    alongside it, because not every review comes from an account: testimonials
    collected before launch or imported from another platform still have to
    render identically to a logged in learner's.

    Nothing is shown publicly until `status` reaches `approved` - a course
    landing page is the last place an unmoderated comment should appear.
    """

    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="The account that wrote this; NULL for guest or imported reviews.",
    )

    # -- Who is speaking ---------------------------------------------------
    reviewer_name: Mapped[str | None] = mapped_column(
        String(REVIEW_NAME_MAX_LENGTH),
        default=None,
        doc="Display name, kept even when the account is later removed.",
    )
    reviewer_email: Mapped[str | None] = mapped_column(
        String(REVIEW_EMAIL_MAX_LENGTH), default=None
    )
    reviewer_designation: Mapped[str | None] = mapped_column(String(255), default=None)
    reviewer_avatar: Mapped[str | None] = mapped_column(String(500), default=None)

    # -- The review itself -------------------------------------------------
    rating: Mapped[Decimal] = mapped_column(
        Numeric(2, 1),
        nullable=False,
        index=True,
        doc="One decimal place, so half star ratings are representable.",
    )
    title: Mapped[str | None] = mapped_column(
        String(REVIEW_TITLE_MAX_LENGTH), default=None
    )
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    video_url: Mapped[str | None] = mapped_column(
        String(500), default=None, doc="Video testimonial, where one was recorded."
    )

    # -- Moderation --------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20),
        default=ReviewStatus.PENDING.value,
        server_default=ReviewStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        default=ReviewSource.WEB.value,
        server_default=ReviewSource.WEB.value,
        nullable=False,
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_verified_purchase: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether the reviewer was actually enrolled when they wrote this.",
    )
    moderated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    moderated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Engagement --------------------------------------------------------
    helpful_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    unhelpful_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    report_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # -- Instructor reply --------------------------------------------------
    reply: Mapped[str | None] = mapped_column(Text, default=None)
    replied_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    ip_address: Mapped[str | None] = mapped_column(INET, default=None)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    reviewer: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [Review.user_id]
    )

    __table_args__ = (
        CheckConstraint(
            f"rating >= {REVIEW_MIN_RATING} AND rating <= {REVIEW_MAX_RATING}",
            name="review_rating_range",
        ),
        # Every public read is "approved reviews for this course, newest
        # first"; the average rating aggregates over the same slice.
        Index("ix_reviews_course_id_status", "course_id", "status"),
    )

    @property
    def is_approved(self) -> bool:
        return self.status == ReviewStatus.APPROVED

    def __repr__(self) -> str:
        return f"<Review course={self.course_id} rating={self.rating}>"
