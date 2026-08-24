"""Ticket message model: one entry in a ticket's conversation."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.users.models.user import User


class SupportTicketMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A reply, an internal note, or a line written by the system.

    Three kinds of entry share one table because they share one ordering: an
    agent reading the thread needs the note they left between two replies to
    appear between them. `is_internal_note` is the only thing standing
    between a private remark and the student who raised the ticket, so every
    read path filters on it rather than trusting the caller to.
    """

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Author. Null for a system message, or once the account is gone.",
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Staff only. Never returned to the student who raised the ticket.",
    )
    is_system_message: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Written by the platform, e.g. 'Assigned to Rafiqul Islam'.",
    )

    # -- Audit ---------------------------------------------------------------
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    author: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicketMessage.user_id]
    )

    __table_args__ = (
        # The thread read, in order. Every message view filters by ticket and
        # sorts by time, and a student's view adds `is_internal_note = false`.
        Index(
            "ix_support_ticket_messages_ticket_id_created_at",
            "ticket_id",
            "created_at",
        ),
    )

    @property
    def is_visible_to_student(self) -> bool:
        return not self.is_internal_note

    def __repr__(self) -> str:
        kind = "note" if self.is_internal_note else "reply"
        return f"<SupportTicketMessage {kind} ticket={self.ticket_id}>"
