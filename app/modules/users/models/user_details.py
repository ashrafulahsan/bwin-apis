"""Extended profile and employment details for a user."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.users.models.user import User


class UserDetails(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Optional extended details belonging to one platform user."""

    __tablename__ = "user_details"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gender: Mapped[str | None] = mapped_column(String(50), default=None)
    date_of_birth: Mapped[date | None] = mapped_column(Date, default=None)
    nationality: Mapped[str | None] = mapped_column(String(100), default=None)
    address: Mapped[str | None] = mapped_column(Text, default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    country: Mapped[str | None] = mapped_column(String(100), default=None)
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(50), default=None
    )
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), default=None
    )
    reporting_to: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    designation: Mapped[str | None] = mapped_column(String(255), default=None)
    department: Mapped[str | None] = mapped_column(String(255), default=None)
    organization: Mapped[str | None] = mapped_column(String(255), default=None)
    years_of_experience: Mapped[int | None] = mapped_column(Integer, default=None)
    highest_degree: Mapped[str | None] = mapped_column(String(255), default=None)
    university: Mapped[str | None] = mapped_column(String(255), default=None)
    graduation_year: Mapped[int | None] = mapped_column(Integer, default=None)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), default=None)
    youtube_url: Mapped[str | None] = mapped_column(String(500), default=None)
    facebook_url: Mapped[str | None] = mapped_column(String(500), default=None)
    website_url: Mapped[str | None] = mapped_column(String(500), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    user: Mapped["User"] = relationship(
        back_populates="details", foreign_keys=[user_id]
    )
    manager: Mapped["User | None"] = relationship(
        foreign_keys=[reporting_to], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_details_user_id"),
    )
