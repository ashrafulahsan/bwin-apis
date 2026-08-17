"""Activity log endpoints.

Read-only: there is no POST, PUT or DELETE here, and there is not meant to be
one. Entries are written by `ActivityLogService` from inside the services that
made the change, which is what lets the trail be trusted.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.activity_logs.models.activity_log import (
    ActivityModule,
    ActivityStatus,
)
from app.modules.activity_logs.permissions import can_view
from app.modules.activity_logs.schemas.activity_log import (
    ActivityLogRead,
    ActivityLogSummary,
)
from app.modules.activity_logs.services.activity_log import ActivityLogQueryService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/activity-logs",
    tags=["Activity Log"],
    dependencies=[can_view()],
)

EntryId = Annotated[uuid.UUID, Path(description="Activity log entry identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[ActivityLogSummary]],
    summary="List activity",
    description=(
        "Paginated audit trail, newest first. Every filter is optional and "
        "they combine, so `?module=blogs&action=delete&status=failure` reads "
        "as one question."
    ),
)
async def list_activity(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    user_id: Annotated[
        uuid.UUID | None, Query(description="Only actions taken by this account.")
    ] = None,
    module: Annotated[
        ActivityModule | None, Query(description="Only this part of the platform.")
    ] = None,
    action: Annotated[
        str | None, Query(description="Only this action, e.g. `delete`.")
    ] = None,
    entity_type: Annotated[
        str | None, Query(description="Only this kind of record, e.g. `Blog`.")
    ] = None,
    entity_id: Annotated[str | None, Query(description="Only this record.")] = None,
    status_filter: Annotated[
        ActivityStatus | None,
        Query(alias="status", description="Only successes, or only refusals."),
    ] = None,
    since: Annotated[
        datetime | None, Query(description="Entries recorded at or after this moment.")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Entries recorded at or before this moment.")
    ] = None,
) -> APIResponse[Page[ActivityLogSummary]]:
    items, total = await ActivityLogQueryService(db).list_entries(
        pagination,
        search=search.search,
        user_id=user_id,
        module=module,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        status=status_filter,
        since=since,
        until=until,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [ActivityLogSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Activity fetched",
    )


@router.get(
    "/history/{entity_type}/{entity_id}",
    response_model=APIResponse[list[ActivityLogRead]],
    summary="History of one record",
    description=(
        "Everything recorded against a single record, newest first - the "
        "question an audit trail is usually opened to answer."
    ),
)
async def entity_history(
    db: DbSession,
    entity_type: Annotated[str, Path(description="Model name, e.g. `Blog`.")],
    entity_id: Annotated[str, Path(description="Identifier of the record.")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> APIResponse[list[ActivityLogRead]]:
    entries = await ActivityLogQueryService(db).history_of(
        entity_type, entity_id, limit=limit
    )

    return success_response(
        data=[ActivityLogRead.model_validate(entry) for entry in entries],
        message="History fetched",
    )


@router.get(
    "/{entry_id}",
    response_model=APIResponse[ActivityLogRead],
    summary="Get an entry",
    description="One entry in full, with the value diff and request metadata.",
)
async def get_entry(db: DbSession, entry_id: EntryId) -> APIResponse[ActivityLogRead]:
    entry = await ActivityLogQueryService(db).get(entry_id)

    return success_response(
        data=ActivityLogRead.model_validate(entry), message="Entry fetched"
    )
