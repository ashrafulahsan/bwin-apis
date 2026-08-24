"""Assignment history: who a ticket moved from, and to.

Append-only, like the status history and the timeline beside it. There is no
`updated_at` and no `deleted_at` for the same reason the activity log has
neither: a history someone can edit is not a history.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UUIDPrimaryKeyMixin
from app.modules.support.constants import TICKET_REASON_MAX_LENGTH
from app.modules.users.models.user import User


class SupportTicketAssignment(Base, UUIDPrimaryKeyMixin):
    """One handover, recorded whether it was the first or the fifth."""

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_from: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        doc="Previous owner; null on the first assignment.",
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="New owner; null when a ticket is returned to the pool.",
    )
    reason: Mapped[str | None] = mapped_column(
        String(TICKET_REASON_MAX_LENGTH), default=None
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="No `updated_at`: nothing may edit a history row.",
    )

    assignee: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [SupportTicketAssignment.assigned_to]
    )

    __table_args__ = (
        Index(
            "ix_support_ticket_assignments_ticket_id_created_at",
            "ticket_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<SupportTicketAssignment ticket={self.ticket_id}>"
