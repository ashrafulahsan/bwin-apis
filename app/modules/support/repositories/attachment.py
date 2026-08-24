"""Data access for ticket attachments."""

import uuid

from sqlalchemy import func, select

from app.core.constants import SortOrder
from app.modules.support.models.support_ticket_attachment import (
    SupportTicketAttachment,
)
from app.shared.repositories.base import BaseRepository
from app.shared.repositories.filters import Filter


class SupportTicketAttachmentRepository(BaseRepository[SupportTicketAttachment]):
    model = SupportTicketAttachment
    default_sort_by = "created_at"

    async def list_for_ticket(
        self, ticket_id: uuid.UUID
    ) -> list[SupportTicketAttachment]:
        return await self.list(
            filters=[Filter.eq("ticket_id", ticket_id)],
            sort_by="created_at",
            sort_order=SortOrder.ASC,
        )

    async def list_for_message(
        self, message_id: uuid.UUID
    ) -> list[SupportTicketAttachment]:
        return await self.list(
            filters=[Filter.eq("message_id", message_id)],
            sort_by="created_at",
            sort_order=SortOrder.ASC,
        )

    async def count_for_ticket(self, ticket_id: uuid.UUID) -> int:
        """Live attachments only - a soft deleted file frees its slot."""
        result = await self.session.execute(
            select(func.count())
            .select_from(SupportTicketAttachment)
            .where(
                SupportTicketAttachment.ticket_id == ticket_id,
                SupportTicketAttachment.deleted_at.is_(None),
            )
        )
        return int(result.scalar_one())
