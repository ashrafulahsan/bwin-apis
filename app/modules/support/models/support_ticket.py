"""Support ticket model: one request for help, and its running state."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from app.modules.categories.models.category import Category
from app.modules.support.constants import (
    FEEDBACK_MAX_RATING,
    FEEDBACK_MIN_RATING,
    TERMINAL_STATUSES,
    TICKET_NO_MAX_LENGTH,
    TICKET_SUBJECT_MAX_LENGTH,
    TicketPriority,
    TicketSource,
    TicketStatus,
)
from app.modules.users.models.user import User


class SupportTicket(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A support request raised by a student.

    The counters and timestamps here - `total_replies`, `last_reply_at`,
    `first_response_at` - are denormalized on purpose. A support queue is read
    far more often than it is written, and every list view wants "how busy is
    this ticket and when did we last touch it" without a correlated subquery
    per row. The service is the only writer, so they cannot drift.

    `first_response_at` is set once, by the first staff reply, and never
    again: it is the numerator of the response-time report, and an agent
    replying a second time must not improve the figure retroactively.
    """

    ticket_no: Mapped[str] = mapped_column(
        String(TICKET_NO_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Human quotable reference, e.g. TKT-2026-000001.",
    )
    subject: Mapped[str] = mapped_column(
        String(TICKET_SUBJECT_MAX_LENGTH), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`: retiring a support topic must not delete the tickets
        # filed under it, which are the record of what was asked.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Who raised it. Their tickets go with the account when it is erased.",
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # `SET NULL`: an agent leaving returns their queue to unassigned
        # rather than destroying it.
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )

    priority: Mapped[str] = mapped_column(
        String(20),
        default=TicketPriority.MEDIUM.value,
        server_default=TicketPriority.MEDIUM.value,
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=TicketStatus.OPEN.value,
        server_default=TicketStatus.OPEN.value,
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        default=TicketSource.WEB.value,
        server_default=TicketSource.WEB.value,
        nullable=False,
    )

    # -- Service level timestamps ------------------------------------------
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        doc="When staff first replied. Written once, never revised.",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    # -- Denormalized counters ---------------------------------------------
    total_replies: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    attachment_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # -- Escalation ---------------------------------------------------------
    is_escalated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    escalated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    escalation_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Satisfaction -------------------------------------------------------
    # Mirrored from `support_ticket_feedback` so a queue listing can show the
    # score without joining; the feedback row remains the record of when it
    # was given and by whom.
    satisfaction_rating: Mapped[int | None] = mapped_column(Integer, default=None)
    satisfaction_comment: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Merging ------------------------------------------------------------
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Set on the duplicate; points at the ticket that absorbed it.",
    )
    merged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # -- Audit ---------------------------------------------------------------
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        doc="Who filed it - differs from `student_id` when an agent files on "
        "a student's behalf.",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    category: Mapped[Category | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicket.category_id]
    )
    student: Mapped[User] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicket.student_id]
    )
    assignee: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicket.assigned_to]
    )

    __table_args__ = (
        CheckConstraint(
            f"satisfaction_rating IS NULL OR (satisfaction_rating >= "
            f"{FEEDBACK_MIN_RATING} AND satisfaction_rating <= {FEEDBACK_MAX_RATING})",
            name="satisfaction_rating_range",
        ),
        # "My queue, worst first" - the screen an agent lives in.
        Index("ix_support_tickets_assigned_to_status", "assigned_to", "status"),
        # "My tickets, newest first" - the screen a student lives in.
        Index("ix_support_tickets_student_id_status", "student_id", "status"),
        # The admin queue and every dashboard count.
        Index("ix_support_tickets_status_priority", "status", "priority"),
        Index("ix_support_tickets_created_at", "created_at"),
    )

    # -- Derived state --------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Whether the ticket is still being worked."""
        return TicketStatus(self.status) not in TERMINAL_STATUSES

    @property
    def is_closed(self) -> bool:
        return self.status == TicketStatus.CLOSED

    @property
    def is_resolved(self) -> bool:
        return self.status == TicketStatus.RESOLVED

    @property
    def is_merged(self) -> bool:
        return self.merged_into_id is not None

    @property
    def is_assigned(self) -> bool:
        return self.assigned_to is not None

    @property
    def response_seconds(self) -> float | None:
        """Time from raising the ticket to the first staff reply."""
        if self.first_response_at is None:
            return None
        return (self.first_response_at - self.created_at).total_seconds()

    @property
    def resolution_seconds(self) -> float | None:
        """Time from raising the ticket to resolving or closing it."""
        finished = self.resolved_at or self.closed_at
        if finished is None:
            return None
        return (finished - self.created_at).total_seconds()

    def __repr__(self) -> str:
        return f"<SupportTicket {self.ticket_no} {self.status}>"
