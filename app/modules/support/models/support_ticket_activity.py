"""Ticket timeline: what happened to one ticket, in the order it happened.

Distinct from the platform's `activity_logs`, and deliberately so. That table
is an audit trail read by administrators, keyed by actor, and it records
things no student should see. This one is the timeline rendered *inside* the
ticket, read by whoever can read the ticket. Merging them would mean either
leaking internal notes into a student's view or hiding assignment history
from an auditor.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKeyMixin
from app.modules.support.constants import (
    ACTIVITY_DESCRIPTION_MAX_LENGTH,
    ACTIVITY_TYPE_MAX_LENGTH,
)


class SupportTicketActivity(Base, UUIDPrimaryKeyMixin):
    """One timeline entry."""

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
    )

    activity_type: Mapped[str] = mapped_column(
        String(ACTIVITY_TYPE_MAX_LENGTH), nullable=False, index=True
    )
    activity_description: Mapped[str] = mapped_column(
        String(ACTIVITY_DESCRIPTION_MAX_LENGTH),
        nullable=False,
        doc="One rendered sentence, written for whoever opens the ticket.",
    )

    # `metadata` is reserved on a declarative class - it is the `MetaData`
    # every model hangs off - so the attribute is named around it while the
    # column keeps the name the schema asks for.
    activity_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        default=None,
        doc="Structured detail behind the sentence: ids, before and after.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="No `updated_at`: nothing may edit a timeline row.",
    )

    __table_args__ = (
        Index(
            "ix_support_ticket_activities_ticket_id_created_at",
            "ticket_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<SupportTicketActivity {self.activity_type}>"
