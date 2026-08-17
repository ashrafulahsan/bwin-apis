"""Reading the activity log.

The write path is `app.shared.services.activity_log_service`, which every
module calls. This is the other half: the queries an administrator runs
against what was written. They are separate classes on purpose - the writer
is imported by every service in the platform and should stay small, and
nothing that reads the log should be one import away from being able to
append to it.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityLog,
    ActivityModule,
    ActivityStatus,
)
from app.modules.activity_logs.repositories.activity_log import ActivityLogRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination


class ActivityLogQueryService:
    """Read-only access to the audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ActivityLogRepository(session)

    async def get(self, entry_id: uuid.UUID) -> ActivityLog:
        return await self.repository.get_or_raise(entry_id)

    async def list_entries(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        user_id: uuid.UUID | None = None,
        module: ActivityModule | None = None,
        action: ActivityAction | str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        status: ActivityStatus | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[ActivityLog], int]:
        filters = []

        if user_id is not None:
            filters.append(Filter.eq("user_id", user_id))
        if module is not None:
            filters.append(Filter.eq("module", module.value))
        if action is not None:
            filters.append(Filter.eq("action", str(action)))
        if entity_type is not None:
            filters.append(Filter.eq("entity_type", entity_type))
        if entity_id is not None:
            filters.append(Filter.eq("entity_id", entity_id))
        if status is not None:
            filters.append(Filter.eq("status", status.value))

        return await self.repository.search(
            pagination,
            filters=filters,
            search=search,
            since=since,
            until=until,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def history_of(
        self, entity_type: str, entity_id: str, *, limit: int = 50
    ) -> list[ActivityLog]:
        """Everything recorded against one row, newest first."""
        return await self.repository.history_of(entity_type, entity_id, limit=limit)
