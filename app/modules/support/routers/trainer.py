"""Trainer-facing support endpoints.

A trainer works a queue rather than browsing one, so the routes here are
narrower than the shared listing: `my-tickets` is fixed to their own
assignments and cannot be widened by a query parameter.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.core.constants import SortOrder
from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.support.constants import TicketPriority, TicketStatus
from app.modules.support.permissions import can_change_status, can_view
from app.modules.support.policy import TicketScope
from app.modules.support.schemas.stats import TicketStatistics
from app.modules.support.schemas.ticket import (
    TicketRead,
    TicketStatusChange,
    TicketSummary,
)
from app.modules.support.services.stats import SupportStatsService
from app.modules.support.services.ticket import SupportTicketService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/support", tags=["Support - Trainer"])

TicketId = Annotated[uuid.UUID, Path(description="Ticket identifier.")]


@router.get(
    "/my-tickets",
    response_model=APIResponse[Page[TicketSummary]],
    dependencies=[can_view()],
    summary="List tickets assigned to the caller",
)
async def list_my_tickets(
    db: DbSession,
    user: CurrentUser,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: Annotated[TicketPriority | None, Query()] = None,
) -> APIResponse[Page[TicketSummary]]:
    items, total = await SupportTicketService(db).list_tickets(
        pagination,
        actor=user,
        search=search.search,
        status=ticket_status,
        priority=priority,
        # Fixed here rather than taken from the request: "my tickets" is the
        # point of the route.
        scope=TicketScope.ASSIGNED,
        assigned_to=user.id,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order or SortOrder.DESC,
    )
    return paginated_response(
        [TicketSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Assigned tickets fetched",
    )


@router.get(
    "/my-statistics",
    response_model=APIResponse[TicketStatistics],
    dependencies=[can_view()],
    summary="Dashboard figures for the caller's own queue",
)
async def my_statistics(
    db: DbSession, user: CurrentUser
) -> APIResponse[TicketStatistics]:
    stats = await SupportStatsService(db).dashboard(assigned_to=user.id)
    return success_response(data=stats, message="Statistics fetched")


@router.patch(
    "/tickets/{ticket_id}/status",
    response_model=APIResponse[TicketRead],
    dependencies=[can_change_status()],
    summary="Change a ticket's status",
    description=(
        "Follows the lifecycle: an illegal move, such as `closed` straight "
        "back to `in_progress`, is refused with a 400 naming both states. "
        "Moving to `resolved` stamps `resolved_at`; `closed` and `reopened` "
        "are routed through the close and reopen rules."
    ),
)
async def change_status(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: TicketStatusChange
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).change_status(
        ticket_id, payload, actor=user
    )
    return success_response(
        data=TicketRead.from_model(ticket), message="Status updated"
    )
