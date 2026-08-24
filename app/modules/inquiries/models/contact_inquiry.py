"""Contact inquiry model: one submission of the website contact form."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.inquiries.constants import (
    CLOSED_STATUSES,
    INQUIRY_EMAIL_MAX_LENGTH,
    INQUIRY_INTEREST_MAX_LENGTH,
    INQUIRY_IP_MAX_LENGTH,
    INQUIRY_NAME_MAX_LENGTH,
    INQUIRY_PHONE_MAX_LENGTH,
    INQUIRY_STATUS_MAX_LENGTH,
    InquiryStatus,
    InterestedIn,
)
from app.modules.users.models.user import User


class ContactInquiry(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Someone who filled in the contact form.

    Every inquiry form on the site writes here rather than to a table of its
    own: they ask the same four questions, and one table is what makes "how
    many people asked about consultancy last month" a query instead of a
    union.

    The row is personal data volunteered by someone who is not a user of the
    platform, which shapes two decisions. It is soft deleted, so a removal
    request leaves a record that the removal happened. And `ip_address` and
    `user_agent` are kept only because they are what makes abuse of a public
    form traceable - nothing else reads them.
    """

    full_name: Mapped[str] = mapped_column(
        String(INQUIRY_NAME_MAX_LENGTH), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(INQUIRY_EMAIL_MAX_LENGTH),
        nullable=False,
        index=True,
        doc="Lowercased on the way in, so the same person matches themselves.",
    )
    phone: Mapped[str] = mapped_column(
        String(INQUIRY_PHONE_MAX_LENGTH),
        nullable=False,
        index=True,
        doc="Normalized to E.164, so `01712-345678` and `+8801712345678` match.",
    )
    interested_in: Mapped[str] = mapped_column(
        String(INQUIRY_INTEREST_MAX_LENGTH), nullable=False, index=True
    )
    message: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Handling ----------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(INQUIRY_STATUS_MAX_LENGTH),
        default=InquiryStatus.NEW.value,
        server_default=InquiryStatus.NEW.value,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        doc="Internal. Never returned by any public endpoint.",
    )

    # -- Provenance --------------------------------------------------------
    ip_address: Mapped[str | None] = mapped_column(
        String(INQUIRY_IP_MAX_LENGTH),
        default=None,
        doc="Where the submission came from; also what the rate limit counts.",
    )
    user_agent: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Triage ------------------------------------------------------------
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    read_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        doc="Who opened it first. Every later view is in the activity log.",
    )

    # -- Audit -------------------------------------------------------------
    # No `created_by`: the form is public, and whoever submits it has no
    # account. `updated_by` is set the first time a member of staff touches it.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    reader: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [ContactInquiry.read_by]
    )

    __table_args__ = (
        # The default admin listing: newest first, unread first.
        Index("ix_contact_inquiries_status_created_at", "status", "created_at"),
        Index("ix_contact_inquiries_created_at", "created_at"),
        # What the rate limit checks on every public submission. Without it
        # the guard against flooding the form is itself a table scan, which
        # is a denial of service with extra steps.
        Index("ix_contact_inquiries_ip_address_created_at", "ip_address", "created_at"),
    )

    # -- Derived state -------------------------------------------------------

    @property
    def is_new(self) -> bool:
        return self.status == InquiryStatus.NEW

    @property
    def is_open(self) -> bool:
        """Whether anyone still has work to do on this."""
        return InquiryStatus(self.status) not in CLOSED_STATUSES

    @property
    def is_spam(self) -> bool:
        return self.status == InquiryStatus.SPAM

    @property
    def interest_label(self) -> str:
        """The form wording, for a screen or an export."""
        from app.modules.inquiries.constants import INTEREST_LABELS

        try:
            return INTEREST_LABELS[InterestedIn(self.interested_in)]
        except ValueError:
            # A value that predates a renamed option still has to render.
            return self.interested_in.replace("_", " ").title()

    def __repr__(self) -> str:
        return f"<ContactInquiry {self.email} {self.status}>"
