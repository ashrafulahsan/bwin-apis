"""Data access for the activity log.

Reads only. Rows are written through `ActivityLogService`, which is the whole
point of the module - a second write path is a second vocabulary, and an
audit trail with two vocabularies cannot be queried.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select

from app.core.constants import SortOrder
from app.modules.activity_logs.models.activity_log import ActivityLog
from app.shared.repositories.base import BaseRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination

#: Columns a free-text search looks at. Not `old_values` or `new_values`:
#: those are JSONB, and a `LIKE` across them would scan the whole table to
#: find matches nobody asked for.
ACTIVITY_SEARCH_FIELDS = ("description", "user_name", "entity_id")


class ActivityLogRepository(BaseRepository[ActivityLog]):
    model = ActivityLog
    #: Newest first: an audit trail is read from the end.
    default_sort_by = "created_at"

    async def search(
        self,
        pagination: SupportsPagination,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[ActivityLog], int]:
        """One page of entries plus the total, within an optional date range."""
        conditions = self._conditions(
            filters=filters, search=search, search_fields=list(ACTIVITY_SEARCH_FIELDS)
        )

        if since is not None:
            conditions.append(ActivityLog.created_at >= since)
        if until is not None:
            conditions.append(ActivityLog.created_at <= until)

        total = await self.session.execute(
            select(func.count()).select_from(ActivityLog).where(*conditions)
        )

        statement = self._apply_ordering(
            select(ActivityLog).where(*conditions), sort_by, sort_order
        )
        rows = await self.session.execute(
            statement.offset((pagination.page - 1) * pagination.page_size).limit(
                pagination.page_size
            )
        )

        return list(rows.scalars().all()), int(total.scalar_one())

    async def history_of(
        self, entity_type: str, entity_id: str, *, limit: int = 50
    ) -> list[ActivityLog]:
        """Everything that has happened to one row, newest first.

        The question an audit trail is usually opened to answer: not "what
        happened today" but "who touched this, and what did they change".
        """
        result = await self.session.execute(
            select(ActivityLog)
            .where(
                ActivityLog.entity_type == entity_type,
                ActivityLog.entity_id == entity_id,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_user(
        self, user_id: uuid.UUID, *, since: datetime | None = None
    ) -> int:
        conditions = [ActivityLog.user_id == user_id]
        if since is not None:
            conditions.append(ActivityLog.created_at >= since)

        result = await self.session.execute(
            select(func.count()).select_from(ActivityLog).where(*conditions)
        )
        return int(result.scalar_one())
