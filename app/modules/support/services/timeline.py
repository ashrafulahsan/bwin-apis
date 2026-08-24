"""Recording what happened to a ticket.

Every workflow move writes to three places: the ticket's own timeline, the
history table for that kind of move, and the platform activity log. Doing
that inline in each service method would be a dozen chances to record two of
the three, so it is collected here and the ticket service calls one method
per move.

Nothing in this module commits. It writes into the caller's session so a
ticket change and its history land in the same transaction - a timeline that
survives a rolled-back update describes something that never happened.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.support.constants import TicketActivityType, TicketStatus
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.models.support_ticket_activity import SupportTicketActivity
from app.modules.support.models.support_ticket_assignment import (
    SupportTicketAssignment,
)
from app.modules.support.models.support_ticket_message import SupportTicketMessage
from app.modules.support.models.support_ticket_status_history import (
    SupportTicketStatusHistory,
)
from app.shared.services.activity_log_service import jsonable


class TicketTimeline:
    """Writes a ticket's history, in the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def activity(
        self,
        ticket: SupportTicket,
        activity_type: TicketActivityType,
        description: str,
        *,
        actor_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SupportTicketActivity:
        """Add one line to the timeline shown inside the ticket."""
        entry = SupportTicketActivity(
            ticket_id=ticket.id,
            user_id=actor_id,
            activity_type=activity_type.value,
            activity_description=description,
            activity_metadata=(
                {key: jsonable(value) for key, value in metadata.items()}
                if metadata
                else None
            ),
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def status_change(
        self,
        ticket: SupportTicket,
        *,
        old_status: str | None,
        new_status: str,
        actor_id: uuid.UUID | None = None,
        remarks: str | None = None,
    ) -> SupportTicketStatusHistory:
        """Record a lifecycle move in the status history table."""
        entry = SupportTicketStatusHistory(
            ticket_id=ticket.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=actor_id,
            remarks=remarks,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def assignment(
        self,
        ticket: SupportTicket,
        *,
        assigned_from: uuid.UUID | None,
        assigned_to: uuid.UUID | None,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> SupportTicketAssignment:
        """Record a handover, first or fifth."""
        entry = SupportTicketAssignment(
            ticket_id=ticket.id,
            assigned_from=assigned_from,
            assigned_to=assigned_to,
            reason=reason,
            created_by=actor_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def system_message(
        self, ticket: SupportTicket, message: str, *, actor_id: uuid.UUID | None = None
    ) -> SupportTicketMessage:
        """Drop a system line into the thread itself.

        Used for the moves a reader needs to see *between* the replies -
        "Reopened by the student" is only intelligible where it happened.
        It does not count towards `total_replies`, which measures the
        conversation rather than the bookkeeping around it.
        """
        entry = SupportTicketMessage(
            ticket_id=ticket.id,
            user_id=actor_id,
            message=message,
            is_system_message=True,
            created_by=actor_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry


def describe_status(status: str) -> str:
    """`waiting_for_student` -> `Waiting For Student`, for timeline sentences."""
    return TicketStatus(status).value.replace("_", " ").title()
