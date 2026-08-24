"""Status history: the complete lifecycle of one ticket, one row per move."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKeyMixin
from app.modules.support.constants import TICKET_REMARKS_MAX_LENGTH


class SupportTicketStatusHistory(Base, UUIDPrimaryKeyMixin):
    """One status change.

    `old_status` is null only for the row written when the ticket is created,
    which is what makes the history a complete account rather than a list of
    edits to something whose starting point is unrecorded.
    """

    # The generated plural would be `support_ticket_status_histories`, which
    # reads badly and is not what the rest of the platform calls this table.
    __tablename__ = "support_ticket_status_history"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status: Mapped[str | None] = mapped_column(
        String(30), default=None, doc="Null on the row that records creation."
    )
    new_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    remarks: Mapped[str | None] = mapped_column(
        String(TICKET_REMARKS_MAX_LENGTH), default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="No `updated_at`: nothing may edit a history row.",
    )

    __table_args__ = (
        Index(
            "ix_support_ticket_status_history_ticket_id_created_at",
            "ticket_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<SupportTicketStatusHistory {self.old_status}->{self.new_status}>"
