"""Course FAQ model: a question and answer shown on a course page."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.courses.constants import (
    FAQ_GROUP_MAX_LENGTH,
    FAQ_QUESTION_MAX_LENGTH,
    FaqStatus,
)


class CourseFaq(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One question and its answer, attached to a course.

    `faq_group` is a free text heading rather than a foreign key: the
    groupings authors reach for - "Payment", "Schedule", "Certificate" -
    differ per course and are never queried across them, so a taxonomy table
    would cost more than it explains.
    """

    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question: Mapped[str] = mapped_column(
        String(FAQ_QUESTION_MAX_LENGTH), nullable=False
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    faq_group: Mapped[str | None] = mapped_column(
        String(FAQ_GROUP_MAX_LENGTH),
        default=None,
        index=True,
        doc="Section heading this question is listed under.",
    )

    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=FaqStatus.DRAFT.value,
        server_default=FaqStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # -- Engagement --------------------------------------------------------
    view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    helpful_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    unhelpful_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # -- Audit -------------------------------------------------------------
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    __table_args__ = (
        Index("ix_course_faqs_course_id_sort_order", "course_id", "sort_order"),
    )

    @property
    def is_published(self) -> bool:
        return self.status == FaqStatus.PUBLISHED

    def __repr__(self) -> str:
        return f"<CourseFaq {self.question[:40]}>"
