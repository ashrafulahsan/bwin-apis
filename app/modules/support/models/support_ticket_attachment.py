"""Ticket attachment model: a file uploaded against a ticket or a message."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.support.constants import (
    ATTACHMENT_FILE_NAME_MAX_LENGTH,
    ATTACHMENT_MIME_TYPE_MAX_LENGTH,
    ATTACHMENT_PATH_MAX_LENGTH,
)
from app.modules.users.models.user import User


class SupportTicketAttachment(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin
):
    """One stored file.

    Two names are kept, and the distinction matters for security rather than
    tidiness: `original_name` is whatever the uploader's browser sent and is
    only ever echoed back as a label, while `file_name` is the sanitized name
    actually written to disk. Serving a download by the original name would
    hand a caller control of a path.

    `message_id` is optional: a file may arrive with the ticket itself,
    before any reply exists to hang it on.
    """

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_ticket_messages.id", ondelete="CASCADE"),
        default=None,
        index=True,
        doc="The reply this arrived with; null when attached to the ticket.",
    )

    file_name: Mapped[str] = mapped_column(
        String(ATTACHMENT_FILE_NAME_MAX_LENGTH),
        nullable=False,
        doc="Sanitized name on disk. Never taken from the client.",
    )
    original_name: Mapped[str] = mapped_column(
        String(ATTACHMENT_FILE_NAME_MAX_LENGTH),
        nullable=False,
        doc="What the uploader called it. A label, never a path.",
    )
    file_path: Mapped[str] = mapped_column(
        String(ATTACHMENT_PATH_MAX_LENGTH),
        nullable=False,
        doc="Location relative to the configured upload directory.",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, doc="Bytes, as written."
    )
    mime_type: Mapped[str | None] = mapped_column(
        String(ATTACHMENT_MIME_TYPE_MAX_LENGTH), default=None
    )

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    uploader: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicketAttachment.uploaded_by]
    )

    __table_args__ = (
        Index(
            "ix_support_ticket_attachments_ticket_id_created_at",
            "ticket_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<SupportTicketAttachment {self.original_name}>"
