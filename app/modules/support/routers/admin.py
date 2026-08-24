"""Administrative support endpoints: triage, assignment, reporting, export."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.core.constants import SortOrder
from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.support.constants import TicketPriority, TicketStatus
from app.modules.support.permissions import (
    can_assign,
    can_change_category,
    can_change_priority,
    can_delete,
    can_escalate,
    can_export,
    can_merge,
    can_report,
    can_view_all,
    can_write_internal_note,
)
from app.modules.support.policy import TicketScope
from app.modules.support.schemas.message import InternalNoteCreate
from app.modules.support.schemas.stats import TicketStatistics
from app.modules.support.schemas.ticket import (
    AdminTicketCreate,
    AssignmentRead,
    MessageRead,
    StatusHistoryRead,
    TicketAssign,
    TicketCategoryChange,
    TicketEscalate,
    TicketMerge,
    TicketPriorityChange,
    TicketRead,
    TicketSummary,
)
from app.modules.support.services.export import SupportExportService
from app.modules.support.services.stats import SupportStatsService
from app.modules.support.services.ticket import SupportTicketService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/support", tags=["Support - Admin"])

TicketId = Annotated[uuid.UUID, Path(description="Ticket identifier.")]


@router.get(
    "/admin/tickets",
    response_model=APIResponse[Page[TicketSummary]],
    dependencies=[can_view_all()],
    summary="List every ticket",
    description=(
        "The full queue, with the triage filters an administrator works "
        "from - including `unassigned=true` for the backlog nobody owns."
    ),
)
async def list_all_tickets(
    db: DbSession,
    user: CurrentUser,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: Annotated[TicketPriority | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    is_escalated: Annotated[bool | None, Query()] = None,
    unassigned: Annotated[
        bool, Query(description="Only tickets with no owner.")
    ] = False,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[Page[TicketSummary]]:
    items, total = await SupportTicketService(db).list_tickets(
        pagination,
        actor=user,
        search=search.search,
        status=ticket_status,
        priority=priority,
        category_id=category_id,
        student_id=student_id,
        assigned_to=assigned_to,
        is_escalated=is_escalated,
        unassigned=unassigned,
        date_from=date_from,
        date_to=date_to,
        scope=TicketScope.ALL,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order or SortOrder.DESC,
    )
    return paginated_response(
        [TicketSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Tickets fetched",
    )


@router.post(
    "/admin/tickets",
    response_model=APIResponse[TicketRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_assign()],
    summary="Raise a ticket on a student's behalf",
)
async def create_for_student(
    db: DbSession, user: CurrentUser, payload: AdminTicketCreate
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).create_for_student(payload, actor=user)
    return created_response(
        data=TicketRead.from_model(ticket), message="Ticket created"
    )


@router.patch(
    "/tickets/{ticket_id}/assign",
    response_model=APIResponse[TicketRead],
    dependencies=[can_assign()],
    summary="Assign or reassign a ticket",
    description=(
        "Every handover is recorded in `support_ticket_assignments`. Passing "
        "`assigned_to: null` returns the ticket to the unassigned pool."
    ),
)
async def assign_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: TicketAssign
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).assign(ticket_id, payload, actor=user)
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket assigned"
    )


@router.patch(
    "/tickets/{ticket_id}/priority",
    response_model=APIResponse[TicketRead],
    dependencies=[can_change_priority()],
    summary="Change a ticket's priority",
)
async def change_priority(
    db: DbSession,
    user: CurrentUser,
    ticket_id: TicketId,
    payload: TicketPriorityChange,
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).change_priority(
        ticket_id, payload, actor=user
    )
    return success_response(
        data=TicketRead.from_model(ticket), message="Priority updated"
    )


@router.patch(
    "/tickets/{ticket_id}/category",
    response_model=APIResponse[TicketRead],
    dependencies=[can_change_category()],
    summary="Refile a ticket under another category",
)
async def change_category(
    db: DbSession,
    user: CurrentUser,
    ticket_id: TicketId,
    payload: TicketCategoryChange,
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).change_category(
        ticket_id, payload, actor=user
    )
    return success_response(
        data=TicketRead.from_model(ticket), message="Category updated"
    )


@router.patch(
    "/tickets/{ticket_id}/escalate",
    response_model=APIResponse[TicketRead],
    dependencies=[can_escalate()],
    summary="Escalate a ticket",
    description=(
        "Flags the ticket, moves it to `escalated`, and optionally hands it "
        "to someone in the same act. A ticket can only be escalated once."
    ),
)
async def escalate_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: TicketEscalate
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).escalate(ticket_id, payload, actor=user)
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket escalated"
    )


@router.post(
    "/tickets/{ticket_id}/internal-note",
    response_model=APIResponse[MessageRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_write_internal_note()],
    summary="Add a staff-only note",
    description=(
        "Never returned to the student, and never counted as a reply. A "
        "separate route from `/reply` on purpose: privacy should not depend "
        "on a boolean in a request body."
    ),
)
async def add_internal_note(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: InternalNoteCreate
) -> APIResponse[MessageRead]:
    note = await SupportTicketService(db).reply(
        ticket_id, payload.message, actor=user, is_internal_note=True
    )
    return created_response(
        data=MessageRead.model_validate(note), message="Internal note added"
    )


@router.post(
    "/tickets/{ticket_id}/merge",
    response_model=APIResponse[TicketRead],
    dependencies=[can_merge()],
    summary="Merge a duplicate into another ticket",
    description=(
        "Moves this ticket's messages and attachments onto the target, then "
        "closes it with a pointer to where the conversation went. The "
        "duplicate is kept so its number still resolves."
    ),
)
async def merge_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: TicketMerge
) -> APIResponse[TicketRead]:
    target = await SupportTicketService(db).merge(ticket_id, payload, actor=user)
    return success_response(data=TicketRead.from_model(target), message="Ticket merged")


@router.get(
    "/tickets/{ticket_id}/assignments",
    response_model=APIResponse[list[AssignmentRead]],
    dependencies=[can_view_all()],
    summary="Read a ticket's assignment history",
)
async def list_assignments(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[list[AssignmentRead]]:
    service = SupportTicketService(db)
    await service.get(ticket_id, actor=user)
    rows = await service.assignments.list_for_ticket(ticket_id)
    return success_response(
        data=[AssignmentRead.model_validate(row) for row in rows],
        message="Assignment history fetched",
    )


@router.get(
    "/tickets/{ticket_id}/status-history",
    response_model=APIResponse[list[StatusHistoryRead]],
    dependencies=[can_view_all()],
    summary="Read a ticket's status history",
)
async def list_status_history(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[list[StatusHistoryRead]]:
    service = SupportTicketService(db)
    await service.get(ticket_id, actor=user)
    rows = await service.status_history.list_for_ticket(ticket_id)
    return success_response(
        data=[StatusHistoryRead.model_validate(row) for row in rows],
        message="Status history fetched",
    )


@router.delete(
    "/tickets/{ticket_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Soft delete a ticket",
)
async def delete_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[None]:
    await SupportTicketService(db).delete(ticket_id, actor=user)
    return deleted_response("Ticket deleted")


@router.post(
    "/tickets/{ticket_id}/restore",
    response_model=APIResponse[TicketRead],
    dependencies=[can_delete()],
    summary="Restore a deleted ticket",
)
async def restore_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).restore(ticket_id, actor=user)
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket restored"
    )


# -- Reporting ------------------------------------------------------------


@router.get(
    "/reports",
    response_model=APIResponse[TicketStatistics],
    dependencies=[can_report()],
    summary="Support dashboard statistics",
    description=(
        "Counts by status, priority and category, plus average first "
        "response and resolution times. Durations are given in seconds and "
        "in hours; both are null until there is something to average."
    ),
)
async def support_reports(
    db: DbSession,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[TicketStatistics]:
    stats = await SupportStatsService(db).dashboard(
        date_from=date_from, date_to=date_to
    )
    return success_response(data=stats, message="Report generated")


@router.get(
    "/reports/export",
    dependencies=[can_export()],
    summary="Export the ticket queue as CSV",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "A CSV document of the filtered queue.",
        }
    },
)
async def export_tickets(
    db: DbSession,
    user: CurrentUser,
    search: SearchDep,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: Annotated[TicketPriority | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    is_escalated: Annotated[bool | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> Response:
    body = await SupportExportService(db).export_csv(
        actor=user,
        search=search.search,
        status=ticket_status,
        priority=priority,
        category_id=category_id,
        student_id=student_id,
        assigned_to=assigned_to,
        is_escalated=is_escalated,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="support-tickets.csv"'},
    )
