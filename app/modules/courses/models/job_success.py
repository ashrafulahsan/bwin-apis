"""Job success model: a placement story told against the course behind it."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
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
from app.modules.courses.constants import (
    JOB_SUCCESS_NAME_MAX_LENGTH,
    JOB_SUCCESS_TITLE_MAX_LENGTH,
    JobSuccessStatus,
    JobType,
    SalaryPeriod,
    WorkMode,
)
from app.modules.users.models.user import User


class JobSuccess(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A graduate who took this course and was hired afterwards.

    The student's name, photo and employer are stored on the row rather than
    read through `student_id`, because the story has to keep rendering after
    the account is closed - and many of these are collected from alumni who
    never had an account here at all.

    Salary is split into an amount, a currency and a period so figures stay
    comparable, with `is_salary_public` deciding whether the number is shown
    or only the fact of the hire.
    """

    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )

    # -- The graduate ------------------------------------------------------
    student_name: Mapped[str] = mapped_column(
        String(JOB_SUCCESS_NAME_MAX_LENGTH), nullable=False
    )
    student_email: Mapped[str | None] = mapped_column(String(255), default=None)
    student_phone: Mapped[str | None] = mapped_column(String(30), default=None)
    student_photo: Mapped[str | None] = mapped_column(String(500), default=None)
    student_linkedin_url: Mapped[str | None] = mapped_column(String(500), default=None)
    batch_name: Mapped[str | None] = mapped_column(String(100), default=None)

    # -- The employer ------------------------------------------------------
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_logo_url: Mapped[str | None] = mapped_column(String(500), default=None)
    company_website: Mapped[str | None] = mapped_column(String(500), default=None)
    industry: Mapped[str | None] = mapped_column(String(150), default=None)

    # -- The role ----------------------------------------------------------
    job_title: Mapped[str] = mapped_column(
        String(JOB_SUCCESS_TITLE_MAX_LENGTH), nullable=False
    )
    job_type: Mapped[str] = mapped_column(
        String(20),
        default=JobType.FULL_TIME.value,
        server_default=JobType.FULL_TIME.value,
        nullable=False,
    )
    work_mode: Mapped[str] = mapped_column(
        String(20),
        default=WorkMode.ONSITE.value,
        server_default=WorkMode.ONSITE.value,
        nullable=False,
    )
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    city: Mapped[str | None] = mapped_column(String(150), default=None)
    country: Mapped[str | None] = mapped_column(String(100), default=None)

    # -- Compensation ------------------------------------------------------
    salary_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    salary_currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD", nullable=False
    )
    salary_period: Mapped[str] = mapped_column(
        String(20),
        default=SalaryPeriod.MONTHLY.value,
        server_default=SalaryPeriod.MONTHLY.value,
        nullable=False,
    )
    is_salary_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # -- Before and after --------------------------------------------------
    previous_role: Mapped[str | None] = mapped_column(String(255), default=None)
    previous_company: Mapped[str | None] = mapped_column(String(255), default=None)
    hired_at: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    days_to_hire: Mapped[int | None] = mapped_column(
        Integer,
        default=None,
        doc="Days between finishing the course and accepting the offer.",
    )

    # -- The story ---------------------------------------------------------
    story: Mapped[str | None] = mapped_column(Text, default=None)
    quote: Mapped[str | None] = mapped_column(
        Text, default=None, doc="Short pull quote for a testimonial card."
    )
    video_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # -- Lifecycle ---------------------------------------------------------
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether someone confirmed the placement before publishing it.",
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=JobSuccessStatus.DRAFT.value,
        server_default=JobSuccessStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # -- Audit -------------------------------------------------------------
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    student: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [JobSuccess.student_id]
    )

    __table_args__ = (
        Index("ix_job_successes_course_id_status", "course_id", "status"),
    )

    @property
    def is_published(self) -> bool:
        return self.status == JobSuccessStatus.PUBLISHED

    def __repr__(self) -> str:
        return f"<JobSuccess {self.student_name} @ {self.company_name}>"
