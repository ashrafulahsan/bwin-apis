"""Project model: a piece of work learners build during a course."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
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
    PROJECT_SLUG_MAX_LENGTH,
    PROJECT_TITLE_MAX_LENGTH,
    ProjectStatus,
    ProjectType,
)


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A project a course promises its learners they will build.

    These sell the course as much as they structure it: the landing page
    lists them to show what someone walks away having made. `features` is the
    bullet list shown under each one, kept as JSON because it is only ever
    read and written whole, never queried across projects.
    """

    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(PROJECT_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str | None] = mapped_column(
        String(PROJECT_SLUG_MAX_LENGTH), default=None, index=True
    )
    short_description: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    features: Mapped[list | None] = mapped_column(
        JSON, default=None, doc="What the finished project does, as a bullet list."
    )
    technologies: Mapped[list | None] = mapped_column(
        JSON, default=None, doc="Languages, frameworks and services it uses."
    )
    tools: Mapped[list | None] = mapped_column(JSON, default=None)
    deliverables: Mapped[list | None] = mapped_column(JSON, default=None)
    evaluation_criteria: Mapped[list | None] = mapped_column(JSON, default=None)

    # -- Presentation ------------------------------------------------------
    thumbnail: Mapped[str | None] = mapped_column(String(500), default=None)
    cover_image: Mapped[str | None] = mapped_column(String(500), default=None)
    images: Mapped[list | None] = mapped_column(
        JSON, default=None, doc="Gallery shots as [{url, caption}]."
    )
    demo_url: Mapped[str | None] = mapped_column(String(500), default=None)
    source_code_url: Mapped[str | None] = mapped_column(String(500), default=None)
    video_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # -- Shape of the work -------------------------------------------------
    project_type: Mapped[str] = mapped_column(
        String(20),
        default=ProjectType.INDIVIDUAL.value,
        server_default=ProjectType.INDIVIDUAL.value,
        nullable=False,
    )
    difficulty_level: Mapped[str | None] = mapped_column(
        String(20), default=None, doc="beginner, intermediate or advanced."
    )
    estimated_hours: Mapped[int | None] = mapped_column(Integer, default=None)
    max_score: Mapped[int | None] = mapped_column(Integer, default=None)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=ProjectStatus.DRAFT.value,
        server_default=ProjectStatus.DRAFT.value,
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

    __table_args__ = (
        Index("ix_projects_course_id_sort_order", "course_id", "sort_order"),
    )

    @property
    def is_published(self) -> bool:
        return self.status == ProjectStatus.PUBLISHED

    def __repr__(self) -> str:
        return f"<Project {self.title}>"
