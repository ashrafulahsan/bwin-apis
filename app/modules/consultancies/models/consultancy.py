"""Consultancy model."""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.models.category import Category
from app.modules.consultancies.constants import (
    CONSULTANCY_CODE_MAX_LENGTH,
    CONSULTANCY_IMAGE_URL_MAX_LENGTH,
    CONSULTANCY_SLUG_MAX_LENGTH,
    CONSULTANCY_TITLE_MAX_LENGTH,
    ConsultancyStatus,
    ConsultancyType,
)
from app.modules.users.models.user import User
from app.shared.models.seo import SEOFieldsMixin


class Consultancy(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SEOFieldsMixin
):
    """A consultancy service catalogue entry."""

    consultancy_code: Mapped[str] = mapped_column(
        String(CONSULTANCY_CODE_MAX_LENGTH), unique=True, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(CONSULTANCY_TITLE_MAX_LENGTH), nullable=False
    )
    slug: Mapped[str] = mapped_column(
        String(CONSULTANCY_SLUG_MAX_LENGTH), unique=True, index=True, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    consultancy_type: Mapped[str] = mapped_column(
        String(30),
        default=ConsultancyType.GENERAL.value,
        server_default=ConsultancyType.GENERAL.value,
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    thumbnail: Mapped[str | None] = mapped_column(
        String(CONSULTANCY_IMAGE_URL_MAX_LENGTH), default=None
    )
    promo_video_url: Mapped[str | None] = mapped_column(
        String(CONSULTANCY_IMAGE_URL_MAX_LENGTH), default=None
    )
    sort_order: Mapped[int] = mapped_column(
        default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=ConsultancyStatus.ACTIVE.value,
        server_default=ConsultancyStatus.ACTIVE.value,
        nullable=False,
        index=True,
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

    category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=[category_id]
    )
    creator: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[created_by]
    )

    __table_args__ = (
        Index("ix_consultancies_status_sort_order", "status", "sort_order"),
    )

    @property
    def is_active(self) -> bool:
        return self.status == ConsultancyStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<Consultancy {self.slug}>"
