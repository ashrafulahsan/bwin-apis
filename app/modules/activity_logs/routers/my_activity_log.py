"""Self-service activity log: what I have done, not what anyone did.

Separate from `activity_log.py` on purpose - that router's `can_view()`
dependency is declared once at the router level and applies to every route in
it, so a self-service endpoint cannot live there without loosening that guard
for everyone. This router carries no permission dependency at all: holding a
valid access token is the whole check, exactly like `/auth/me`, and `user_id`
is never accepted from the caller - it always comes from the token, so there
is no way to ask for anyone else's trail through this endpoint.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.activity_logs.models.activity_log import (
    ActivityModule,
    ActivityStatus,
)
from app.modules.activity_logs.schemas.activity_log import ActivityLogSummary
from app.modules.activity_logs.services.activity_log import ActivityLogQueryService
from app.modules.auth.dependencies import CurrentUser
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import APIResponse, paginated_response

router = APIRouter(prefix="/my-activity-logs", tags=["Activity Log"])


@router.get(
    "",
    response_model=APIResponse[Page[ActivityLogSummary]],
    summary="List your own activity",
    description=(
        "Paginated audit trail of actions taken on your account, newest "
        "first. Every filter is optional and they combine, so "
        "`?module=blogs&action=delete` reads as one question. Available to "
        "any signed-in user regardless of role - unlike `/activity-logs`, "
        "there is no `user_id` filter and no permission required beyond "
        "being signed in, because this only ever returns your own entries."
    ),
)
async def list_my_activity(
    db: DbSession,
    user: CurrentUser,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
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
        user_id=user.id,
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
