"""Satisfaction survey: how the student rated the handling of their ticket."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKeyMixin
from app.modules.support.constants import FEEDBACK_MAX_RATING, FEEDBACK_MIN_RATING


class SupportTicketFeedback(Base, UUIDPrimaryKeyMixin):
    """One survey response, at most one per ticket.

    The unique constraint on `ticket_id` is the rule "one feedback per
    ticket" written where it cannot be bypassed. The service checks first so
    the caller gets a sentence rather than an integrity error, but two
    requests arriving together are stopped here.
    """

    __tablename__ = "support_ticket_feedback"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False, doc="1 to 5, enforced by the check constraint."
    )
    feedback: Mapped[str | None] = mapped_column(Text, default=None)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"rating >= {FEEDBACK_MIN_RATING} AND rating <= {FEEDBACK_MAX_RATING}",
            name="feedback_rating_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<SupportTicketFeedback ticket={self.ticket_id} rating={self.rating}>"
