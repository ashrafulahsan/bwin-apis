"""Data access for support tickets, including the dashboard aggregates."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Row, func, select, text

from app.modules.support.constants import (
    TERMINAL_STATUSES,
    TICKET_NO_PREFIX,
    TICKET_NO_SEQUENCE_DIGITS,
    TicketStatus,
)
from app.modules.support.models.support_ticket import SupportTicket
from app.shared.repositories.base import BaseRepository


class SupportTicketRepository(BaseRepository[SupportTicket]):
    model = SupportTicket

    async def get_by_ticket_no(self, ticket_no: str) -> SupportTicket | None:
        return await self.get_by_field("ticket_no", ticket_no)

    async def ticket_no_exists(self, ticket_no: str) -> bool:
        result = await self.session.execute(
            select(
                select(SupportTicket.id)
                .where(SupportTicket.ticket_no == ticket_no)
                .exists()
            )
        )
        return bool(result.scalar_one())

    # -- Numbering -------------------------------------------------------

    async def next_ticket_no(self, year: int) -> str:
        """Reserve the next serial for `year`, e.g. `TKT-2026-000042`.

        Two requests arriving together would otherwise read the same maximum
        and produce the same number, so the read is serialized behind a
        transaction-scoped advisory lock keyed on the year. The lock is
        released when the transaction ends, whichever way it ends, and it
        blocks only other ticket creations in the same year.

        The unique index on `ticket_no` is still the last word: this makes
        collisions not happen, it does not rely on them being impossible.
        """
        prefix = f"{TICKET_NO_PREFIX}-{year}-"

        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"support_ticket_no:{year}"},
        )

        # `split_part` rather than a substring offset: it does not depend on
        # how long the prefix happens to be, and the counter is compared as a
        # number so 000010 sorts after 000009 instead of lexically before it.
        result = await self.session.execute(
            text("""
                SELECT COALESCE(
                    MAX(split_part(ticket_no, '-', 3)::bigint), 0
                )
                FROM support_tickets
                WHERE ticket_no LIKE :pattern
                """),
            {"pattern": f"{prefix}%"},
        )
        highest = int(result.scalar_one() or 0)

        return f"{prefix}{highest + 1:0{TICKET_NO_SEQUENCE_DIGITS}d}"

    # -- Counter maintenance ---------------------------------------------

    async def bump_counters(
        self,
        ticket: SupportTicket,
        *,
        replies: int = 0,
        attachments: int = 0,
    ) -> None:
        """Adjust the denormalized counters in the database, not in Python.

        `total_replies = total_replies + 1` as SQL rather than reading the
        value and writing it back: two replies landing at once would
        otherwise both read the same number and one increment would vanish.
        """
        if not replies and not attachments:
            return

        values: dict[str, Any] = {}
        if replies:
            values["total_replies"] = SupportTicket.total_replies + replies
        if attachments:
            values["attachment_count"] = SupportTicket.attachment_count + attachments

        for field, expression in values.items():
            setattr(ticket, field, expression)

        await self.session.flush()
        await self.session.refresh(ticket)

    # -- Dashboard aggregates ---------------------------------------------

    def _window(
        self, date_from: datetime | None, date_to: datetime | None
    ) -> list[Any]:
        conditions: list[Any] = [SupportTicket.deleted_at.is_(None)]
        if date_from is not None:
            conditions.append(SupportTicket.created_at >= date_from)
        if date_to is not None:
            conditions.append(SupportTicket.created_at <= date_to)
        return conditions

    async def count_by_status(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        assigned_to: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Ticket counts keyed by status, for the dashboard tiles."""
        conditions = self._window(date_from, date_to)
        if assigned_to is not None:
            conditions.append(SupportTicket.assigned_to == assigned_to)

        result = await self.session.execute(
            select(SupportTicket.status, func.count())
            .where(*conditions)
            .group_by(SupportTicket.status)
        )
        counts = {status.value: 0 for status in TicketStatus}
        counts.update({row[0]: int(row[1]) for row in result.all()})
        return counts

    async def count_by_priority(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, int]:
        result = await self.session.execute(
            select(SupportTicket.priority, func.count())
            .where(*self._window(date_from, date_to))
            .group_by(SupportTicket.priority)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def count_by_category(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Sequence[Row[Any]]:
        """Counts per category, with the category name for display."""
        from app.modules.categories.models.category import Category

        result = await self.session.execute(
            select(
                SupportTicket.category_id,
                Category.name,
                func.count(SupportTicket.id),
            )
            .join(Category, Category.id == SupportTicket.category_id, isouter=True)
            .where(*self._window(date_from, date_to))
            .group_by(SupportTicket.category_id, Category.name)
            .order_by(func.count(SupportTicket.id).desc())
        )
        return result.all()

    async def count_escalated(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SupportTicket)
            .where(
                *self._window(date_from, date_to), SupportTicket.is_escalated.is_(True)
            )
        )
        return int(result.scalar_one())

    async def count_unassigned(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Open tickets nobody owns - the number a support lead watches."""
        result = await self.session.execute(
            select(func.count())
            .select_from(SupportTicket)
            .where(
                *self._window(date_from, date_to),
                SupportTicket.assigned_to.is_(None),
                SupportTicket.status.notin_(
                    [status.value for status in TERMINAL_STATUSES]
                ),
            )
        )
        return int(result.scalar_one())

    async def average_response_seconds(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> float | None:
        """Mean seconds from raising a ticket to the first staff reply.

        Averaged in the database over only the tickets that have been
        answered. Counting unanswered ones as zero would make a backlog look
        like excellent service.
        """
        result = await self.session.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch",
                        SupportTicket.first_response_at - SupportTicket.created_at,
                    )
                )
            ).where(
                *self._window(date_from, date_to),
                SupportTicket.first_response_at.is_not(None),
            )
        )
        average = result.scalar_one()
        return float(average) if average is not None else None

    async def average_resolution_seconds(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> float | None:
        """Mean seconds from raising a ticket to resolving it.

        `resolved_at` falls back to `closed_at` for tickets closed without
        passing through resolved - otherwise the shortest journeys, the ones
        closed outright, would be excluded from the figure.
        """
        finished = func.coalesce(SupportTicket.resolved_at, SupportTicket.closed_at)

        result = await self.session.execute(
            select(
                func.avg(func.extract("epoch", finished - SupportTicket.created_at))
            ).where(*self._window(date_from, date_to), finished.is_not(None))
        )
        average = result.scalar_one()
        return float(average) if average is not None else None

    async def average_satisfaction(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> float | None:
        result = await self.session.execute(
            select(func.avg(SupportTicket.satisfaction_rating)).where(
                *self._window(date_from, date_to),
                SupportTicket.satisfaction_rating.is_not(None),
            )
        )
        average = result.scalar_one()
        return float(average) if average is not None else None
