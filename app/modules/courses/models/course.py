"""Course model."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.models.category import Category
from app.modules.courses.constants import (
    COURSE_CODE_MAX_LENGTH,
    COURSE_CURRENCY_MAX_LENGTH,
    COURSE_IMAGE_URL_MAX_LENGTH,
    COURSE_SLUG_MAX_LENGTH,
    COURSE_TITLE_MAX_LENGTH,
    CourseLanguage,
    CourseLevel,
    CourseStatus,
    CourseVisibility,
)
from app.modules.users.models.user import User
from app.shared.models.seo import SEOFieldsMixin
from app.shared.utils.dates import utc_now


class Course(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SEOFieldsMixin
):
    """A publishable course catalogue entry."""

    course_code: Mapped[str] = mapped_column(
        String(COURSE_CODE_MAX_LENGTH), unique=True, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(COURSE_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(COURSE_SLUG_MAX_LENGTH), unique=True, index=True, nullable=False
    )
    short_description: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    learning_outcomes: Mapped[list | None] = mapped_column(JSON, default=None)
    requirements: Mapped[list | None] = mapped_column(JSON, default=None)
    target_audience: Mapped[list | None] = mapped_column(JSON, default=None)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    level: Mapped[str] = mapped_column(
        String(20),
        default=CourseLevel.BEGINNER.value,
        server_default=CourseLevel.BEGINNER.value,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(20),
        default=CourseLanguage.ENGLISH.value,
        server_default=CourseLanguage.ENGLISH.value,
        nullable=False,
    )
    course_type: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    delivery_mode: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )

    thumbnail: Mapped[str | None] = mapped_column(
        String(COURSE_IMAGE_URL_MAX_LENGTH), default=None
    )
    cover_image: Mapped[str | None] = mapped_column(
        String(COURSE_IMAGE_URL_MAX_LENGTH), default=None
    )
    promo_video_url: Mapped[str | None] = mapped_column(
        String(COURSE_IMAGE_URL_MAX_LENGTH), default=None
    )
    intro_video_url: Mapped[str | None] = mapped_column(
        String(COURSE_IMAGE_URL_MAX_LENGTH), default=None
    )

    duration_hours: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_modules: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_lessons: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_quizzes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_assignments: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_resources: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    passing_score: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    certificate_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    certificate_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), default=None
    )
    max_attempts: Mapped[int | None] = mapped_column(Integer, default=None)
    seat_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0", nullable=False
    )
    discount_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    currency: Mapped[str] = mapped_column(
        String(COURSE_CURRENCY_MAX_LENGTH),
        default="USD",
        server_default="USD",
        nullable=False,
    )

    enrollment_start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    enrollment_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    course_start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    course_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=CourseStatus.DRAFT.value,
        server_default=CourseStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(20),
        default=CourseVisibility.PUBLIC.value,
        server_default=CourseVisibility.PUBLIC.value,
        nullable=False,
        index=True,
    )
    featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    allow_reviews: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    allow_discussion: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=[category_id]
    )
    type_category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=[course_type]
    )
    delivery_category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=[delivery_mode]
    )
    creator: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[created_by]
    )

    __table_args__ = (
        Index("ix_courses_status_published_at", "status", "published_at"),
    )

    @property
    def is_published(self) -> bool:
        return self.status == CourseStatus.PUBLISHED

    @property
    def is_live(self) -> bool:
        return (
            self.is_published
            and self.published_at is not None
            and self.published_at <= utc_now()
        )

    @property
    def is_scheduled(self) -> bool:
        return self.is_published and not self.is_live

    def __repr__(self) -> str:
        return f"<Course {self.slug}>"
