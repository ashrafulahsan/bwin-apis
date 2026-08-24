"""Data access for ticket messages, assignments, status history and timeline.

The four append-only tables share a file because they share a shape: written
once by the service, read back in chronological order for one ticket, and
never updated.
"""

import uuid

from sqlalchemy import select

from app.core.constants import SortOrder
from app.modules.support.models.support_ticket_activity import SupportTicketActivity
from app.modules.support.models.support_ticket_assignment import (
    SupportTicketAssignment,
)
from app.modules.support.models.support_ticket_feedback import SupportTicketFeedback
from app.modules.support.models.support_ticket_message import SupportTicketMessage
from app.modules.support.models.support_ticket_status_history import (
    SupportTicketStatusHistory,
)
from app.shared.repositories.base import BaseRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination


class SupportTicketMessageRepository(BaseRepository[SupportTicketMessage]):
    model = SupportTicketMessage
    default_sort_by = "created_at"

    async def list_for_ticket(
        self,
        ticket_id: uuid.UUID,
        *,
        include_internal: bool,
    ) -> list[SupportTicketMessage]:
        """The thread, oldest first.

        `include_internal` is required rather than defaulted: forgetting it
        would leak staff notes to a student, and a parameter with no default
        cannot be forgotten.
        """
        filters = [Filter.eq("ticket_id", ticket_id)]
        if not include_internal:
            filters.append(Filter.eq("is_internal_note", False))

        return await self.list(
            filters=filters, sort_by="created_at", sort_order=SortOrder.ASC
        )

    async def paginate_for_ticket(
        self,
        ticket_id: uuid.UUID,
        pagination: SupportsPagination,
        *,
        include_internal: bool,
    ) -> tuple[list[SupportTicketMessage], int]:
        filters = [Filter.eq("ticket_id", ticket_id)]
        if not include_internal:
            filters.append(Filter.eq("is_internal_note", False))

        return await self.paginate(
            pagination, filters=filters, sort_by="created_at", sort_order=SortOrder.ASC
        )

    async def reassign_to_ticket(
        self, source_ticket_id: uuid.UUID, target_ticket_id: uuid.UUID
    ) -> int:
        """Move a merged ticket's messages onto the ticket that absorbed it."""
        messages = await self.list(filters=[Filter.eq("ticket_id", source_ticket_id)])
        for message in messages:
            message.ticket_id = target_ticket_id

        await self.session.flush()
        return len(messages)


class SupportTicketAssignmentRepository(BaseRepository[SupportTicketAssignment]):
    model = SupportTicketAssignment
    default_sort_by = "created_at"

    async def list_for_ticket(
        self, ticket_id: uuid.UUID
    ) -> list[SupportTicketAssignment]:
        return await self.list(
            filters=[Filter.eq("ticket_id", ticket_id)],
            sort_by="created_at",
            sort_order=SortOrder.ASC,
        )


class SupportTicketStatusHistoryRepository(BaseRepository[SupportTicketStatusHistory]):
    model = SupportTicketStatusHistory
    default_sort_by = "created_at"

    async def list_for_ticket(
        self, ticket_id: uuid.UUID
    ) -> list[SupportTicketStatusHistory]:
        return await self.list(
            filters=[Filter.eq("ticket_id", ticket_id)],
            sort_by="created_at",
            sort_order=SortOrder.ASC,
        )


class SupportTicketActivityRepository(BaseRepository[SupportTicketActivity]):
    model = SupportTicketActivity
    default_sort_by = "created_at"

    async def list_for_ticket(
        self, ticket_id: uuid.UUID, *, limit: int | None = None
    ) -> list[SupportTicketActivity]:
        return await self.list(
            filters=[Filter.eq("ticket_id", ticket_id)],
            sort_by="created_at",
            sort_order=SortOrder.ASC,
            limit=limit,
        )


class SupportTicketFeedbackRepository(BaseRepository[SupportTicketFeedback]):
    model = SupportTicketFeedback
    default_sort_by = "created_at"

    async def get_for_ticket(
        self, ticket_id: uuid.UUID
    ) -> SupportTicketFeedback | None:
        return await self.get_by_field("ticket_id", ticket_id)

    async def exists_for_ticket(self, ticket_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(
                select(SupportTicketFeedback.id)
                .where(SupportTicketFeedback.ticket_id == ticket_id)
                .exists()
            )
        )
        return bool(result.scalar_one())
