"""Course content model: one item in a course curriculum."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.courses.constants import (
    CONTENT_FILE_NAME_MAX_LENGTH,
    CONTENT_SLUG_MAX_LENGTH,
    CONTENT_TITLE_MAX_LENGTH,
    CONTENT_URL_MAX_LENGTH,
    ContentStatus,
    ContentType,
)


class CourseContent(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A single curriculum item: a video, a live class, a file or a quiz.

    All four kinds share one table because a curriculum is read as one
    ordered list - splitting them apart would mean a union query on every
    page load, and `sort_order` would no longer be enforceable across the
    whole course. `content_type` says which of the per-kind column groups
    below carry meaning; the rest stay NULL.

    `parent_id` is what turns the flat list into sections: a row with no
    parent is a module heading, its children are the items inside it.
    """

    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # Content has no meaning without its course, so it goes with it.
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("course_contents.id", ondelete="CASCADE"),
        default=None,
        index=True,
        doc="The section this item sits under; NULL for a top level section.",
    )

    title: Mapped[str] = mapped_column(String(CONTENT_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str | None] = mapped_column(
        String(CONTENT_SLUG_MAX_LENGTH), default=None, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    content_type: Mapped[str] = mapped_column(
        String(20),
        default=ContentType.VIDEO.value,
        server_default=ContentType.VIDEO.value,
        nullable=False,
        index=True,
        doc="Which kind of content this is; selects the meaningful columns.",
    )

    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Playable or expected length, used to total up course duration.",
    )
    is_preview: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Viewable without enrolling, as a taster on the landing page.",
    )
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_downloadable: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # -- Drip release -----------------------------------------------------
    available_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="Absolute unlock time; NULL means available immediately.",
    )
    available_after_days: Mapped[int | None] = mapped_column(
        Integer,
        default=None,
        doc="Unlock this many days after enrolment, for drip fed courses.",
    )

    # -- Pre recorded video -----------------------------------------------
    video_url: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH), default=None
    )
    video_provider: Mapped[str | None] = mapped_column(String(20), default=None)
    video_id: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        doc="Provider side identifier, when the URL is not enough to embed.",
    )
    video_thumbnail: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH), default=None
    )
    video_duration_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    video_quality: Mapped[str | None] = mapped_column(String(20), default=None)
    video_subtitles: Mapped[list | None] = mapped_column(
        JSON, default=None, doc="Subtitle tracks as [{language, label, url}]."
    )
    video_transcript: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Live class -------------------------------------------------------
    live_provider: Mapped[str | None] = mapped_column(String(20), default=None)
    live_meeting_url: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH), default=None
    )
    live_meeting_id: Mapped[str | None] = mapped_column(String(255), default=None)
    live_passcode: Mapped[str | None] = mapped_column(String(100), default=None)
    live_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    live_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    live_timezone: Mapped[str | None] = mapped_column(String(64), default=None)
    live_status: Mapped[str | None] = mapped_column(String(20), default=None)
    live_host_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    live_max_participants: Mapped[int | None] = mapped_column(Integer, default=None)
    live_recording_url: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH),
        default=None,
        doc="Where the session lands once it has ended.",
    )
    live_is_recorded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # -- Document, PDF, PPT, image ----------------------------------------
    file_url: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH), default=None
    )
    file_name: Mapped[str | None] = mapped_column(
        String(CONTENT_FILE_NAME_MAX_LENGTH), default=None
    )
    file_type: Mapped[str | None] = mapped_column(
        String(20), default=None, doc="pdf, doc, ppt, sheet, image or other."
    )
    file_mime_type: Mapped[str | None] = mapped_column(String(150), default=None)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    file_page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    file_thumbnail: Mapped[str | None] = mapped_column(
        String(CONTENT_URL_MAX_LENGTH), default=None
    )

    # -- Quiz --------------------------------------------------------------
    quiz_instructions: Mapped[str | None] = mapped_column(Text, default=None)
    quiz_time_limit_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    quiz_passing_score: Mapped[int | None] = mapped_column(Integer, default=None)
    quiz_max_attempts: Mapped[int | None] = mapped_column(Integer, default=None)
    quiz_total_questions: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    quiz_total_marks: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    quiz_negative_marking: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    quiz_shuffle_questions: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    quiz_show_correct_answers: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    quiz_questions: Mapped[list | None] = mapped_column(
        JSON,
        default=None,
        doc="Question set, until questions earn a table of their own.",
    )

    # -- Anything a kind needs that a column does not cover ----------------
    content_data: Mapped[dict | None] = mapped_column(JSON, default=None)
    attachments: Mapped[list | None] = mapped_column(
        JSON, default=None, doc="Supplementary files as [{name, url, size}]."
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=ContentStatus.DRAFT.value,
        server_default=ContentStatus.DRAFT.value,
        nullable=False,
        index=True,
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

    children: Mapped[list["CourseContent"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by=lambda: CourseContent.sort_order,
    )
    parent: Mapped["CourseContent | None"] = relationship(
        back_populates="children", remote_side=lambda: [CourseContent.id]
    )

    __table_args__ = (
        # The curriculum is always read as "this course, in order".
        Index("ix_course_contents_course_id_sort_order", "course_id", "sort_order"),
        Index("ix_course_contents_course_id_content_type", "course_id", "content_type"),
    )

    @property
    def is_published(self) -> bool:
        return self.status == ContentStatus.PUBLISHED

    def __repr__(self) -> str:
        return f"<CourseContent {self.content_type}:{self.title}>"
