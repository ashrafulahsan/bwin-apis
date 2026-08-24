"""Dashboard statistics for the support desk.

Every figure is computed in the database. The alternative - loading the
tickets and counting in Python - is fine on a demo dataset and falls over on
a real one, and it is the kind of thing that only reveals itself in
production.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.support.constants import TicketPriority, TicketStatus
from app.modules.support.repositories.ticket import SupportTicketRepository
from app.modules.support.schemas.stats import (
    CategoryCount,
    CountByKey,
    TicketStatistics,
)

SECONDS_PER_HOUR = 3600


def _hours(seconds: float | None) -> float | None:
    """Seconds as hours, rounded to two places for display."""
    return None if seconds is None else round(seconds / SECONDS_PER_HOUR, 2)


class SupportStatsService:
    """Builds the support dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SupportTicketRepository(session)

    async def dashboard(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        assigned_to: uuid.UUID | None = None,
    ) -> TicketStatistics:
        """The whole dashboard in one pass.

        `assigned_to` narrows the status tiles to one agent's queue, which is
        what a trainer's own dashboard shows. The averages stay desk-wide on
        purpose: a personal average over three tickets is noise, and reading
        it as performance would be worse than not showing it.
        """
        by_status = await self.repository.count_by_status(
            date_from=date_from, date_to=date_to, assigned_to=assigned_to
        )
        by_priority = await self.repository.count_by_priority(
            date_from=date_from, date_to=date_to
        )
        by_category = await self.repository.count_by_category(
            date_from=date_from, date_to=date_to
        )

        total = sum(by_status.values())
        resolved = by_status.get(TicketStatus.RESOLVED, 0)
        closed = by_status.get(TicketStatus.CLOSED, 0)

        response_seconds = await self.repository.average_response_seconds(
            date_from=date_from, date_to=date_to
        )
        resolution_seconds = await self.repository.average_resolution_seconds(
            date_from=date_from, date_to=date_to
        )

        return TicketStatistics(
            total_tickets=total,
            # "Open" as a business word means "still being worked", not the
            # single `open` status - a ticket waiting on a student is not
            # finished, and a dashboard that says otherwise misleads.
            open_tickets=total - resolved - closed,
            in_progress_tickets=by_status.get(TicketStatus.IN_PROGRESS, 0),
            resolved_tickets=resolved,
            closed_tickets=closed,
            escalated_tickets=await self.repository.count_escalated(
                date_from=date_from, date_to=date_to
            ),
            unassigned_tickets=await self.repository.count_unassigned(
                date_from=date_from, date_to=date_to
            ),
            reopened_tickets=by_status.get(TicketStatus.REOPENED, 0),
            average_response_seconds=response_seconds,
            average_response_hours=_hours(response_seconds),
            average_resolution_seconds=resolution_seconds,
            average_resolution_hours=_hours(resolution_seconds),
            average_satisfaction=await self.repository.average_satisfaction(
                date_from=date_from, date_to=date_to
            ),
            by_status=by_status,
            by_priority=[
                CountByKey(
                    key=priority.value,
                    label=priority.value.replace("_", " ").title(),
                    count=by_priority.get(priority.value, 0),
                )
                for priority in TicketPriority
            ],
            by_category=[
                CategoryCount(
                    category_id=row[0],
                    key=str(row[0]) if row[0] else "uncategorised",
                    label=row[1] or "Uncategorised",
                    count=int(row[2]),
                )
                for row in by_category
            ],
        )
