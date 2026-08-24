"""Exporting the ticket queue as CSV."""

import csv
import io
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.support.constants import TicketPriority, TicketStatus
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.policy import TicketScope
from app.modules.support.services.ticket import SupportTicketService
from app.modules.users.models.user import User
from app.shared.services.activity_log_service import ActivityLogService

#: Cap on one export. A support desk with more rows than this wants a
#: scheduled job writing to storage, not a request holding a connection open
#: while it streams a hundred megabytes.
EXPORT_ROW_LIMIT = 10_000

EXPORT_COLUMNS = [
    "ticket_no",
    "subject",
    "status",
    "priority",
    "category",
    "student",
    "student_email",
    "assigned_to",
    "source",
    "is_escalated",
    "total_replies",
    "attachment_count",
    "satisfaction_rating",
    "created_at",
    "first_response_at",
    "last_reply_at",
    "resolved_at",
    "closed_at",
]


class _Pagination:
    """A one-page window covering the export limit."""

    def __init__(self, limit: int) -> None:
        self.page = 1
        self.page_size = limit


class SupportExportService:
    """Renders a filtered queue as a CSV document."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tickets = SupportTicketService(session)
        self.activity = ActivityLogService(session, ActivityModule.SUPPORT)

    async def export_csv(
        self,
        *,
        actor: User,
        search: str | None = None,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        category_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
        assigned_to: uuid.UUID | None = None,
        is_escalated: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> str:
        """Build the CSV body for the caller's filtered, scoped queue.

        The same scope rules as the listing apply, so an export can never
        return a row its requester could not have opened. That is the whole
        reason this goes through the ticket service rather than the
        repository.
        """
        rows, total = await self.tickets.list_tickets(
            _Pagination(EXPORT_ROW_LIMIT),
            actor=actor,
            search=search,
            status=status,
            priority=priority,
            category_id=category_id,
            student_id=student_id,
            assigned_to=assigned_to,
            is_escalated=is_escalated,
            date_from=date_from,
            date_to=date_to,
            scope=TicketScope.ALL,
            sort_by="created_at",
            sort_order=SortOrder.DESC,
        )

        buffer = io.StringIO()
        # `QUOTE_ALL` so a subject containing a comma, a quote or a newline
        # cannot shift the remaining columns of that row.
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(EXPORT_COLUMNS)

        for ticket in rows:
            writer.writerow(self._row(ticket))

        await self.activity.record(
            ActivityAction.EXPORT,
            entity_type="SupportTicket",
            description=(f"Exported {len(rows)} of {total} support tickets as CSV"),
            new_values={"exported": len(rows), "matched": total},
        )
        await self.session.commit()

        return buffer.getvalue()

    @staticmethod
    def _row(ticket: SupportTicket) -> list[str]:
        def moment(value: datetime | None) -> str:
            return value.isoformat() if value is not None else ""

        return [
            ticket.ticket_no,
            ticket.subject,
            ticket.status,
            ticket.priority,
            ticket.category.name if ticket.category is not None else "",
            ticket.student.full_name if ticket.student is not None else "",
            ticket.student.email if ticket.student is not None else "",
            ticket.assignee.full_name if ticket.assignee is not None else "",
            ticket.source,
            "yes" if ticket.is_escalated else "no",
            str(ticket.total_replies),
            str(ticket.attachment_count),
            (
                str(ticket.satisfaction_rating)
                if ticket.satisfaction_rating is not None
                else ""
            ),
            moment(ticket.created_at),
            moment(ticket.first_response_at),
            moment(ticket.last_reply_at),
            moment(ticket.resolved_at),
            moment(ticket.closed_at),
        ]
