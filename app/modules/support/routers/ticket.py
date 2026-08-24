"""Student-facing support endpoints, plus the shared ticket reads.

Every route here is scoped by the service to what the caller may see, so the
same handler serves a student looking at their own ticket and an
administrator looking at anyone's. Splitting them into separate handlers
would mean two implementations of the same read, and two chances to get the
visibility rules wrong.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Path, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.core.constants import SortOrder
from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.support.constants import TicketPriority, TicketStatus
from app.modules.support.permissions import can_create, can_reply, can_view
from app.modules.support.schemas.message import MessageCreate
from app.modules.support.schemas.ticket import (
    ActivityRead,
    AssignmentRead,
    AttachmentRead,
    FeedbackCreate,
    FeedbackRead,
    MessageRead,
    StatusHistoryRead,
    TicketClose,
    TicketCreate,
    TicketDetail,
    TicketRead,
    TicketReopen,
    TicketSummary,
    TicketUpdate,
)
from app.modules.support.services.attachment import SupportAttachmentService
from app.modules.support.services.ticket import SupportTicketService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/support", tags=["Support"], dependencies=[can_view()])

TicketId = Annotated[uuid.UUID, Path(description="Ticket identifier.")]
AttachmentId = Annotated[uuid.UUID, Path(description="Attachment identifier.")]


@router.get(
    "/tickets",
    response_model=APIResponse[Page[TicketSummary]],
    summary="List tickets visible to the caller",
    description=(
        "Scoped automatically: a student sees the tickets they raised, a "
        "trainer sees the ones assigned to them, and an administrator sees "
        "everything. Filters narrow that slice; they never widen it."
    ),
)
async def list_tickets(
    db: DbSession,
    user: CurrentUser,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    ticket_status: Annotated[
        TicketStatus | None, Query(alias="status", description="Lifecycle state.")
    ] = None,
    priority: Annotated[TicketPriority | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    is_escalated: Annotated[bool | None, Query()] = None,
    date_from: Annotated[
        datetime | None, Query(description="Only tickets raised on or after this.")
    ] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[Page[TicketSummary]]:
    items, total = await SupportTicketService(db).list_tickets(
        pagination,
        actor=user,
        search=search.search,
        status=ticket_status,
        priority=priority,
        category_id=category_id,
        assigned_to=assigned_to,
        is_escalated=is_escalated,
        date_from=date_from,
        date_to=date_to,
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
    "/tickets",
    response_model=APIResponse[TicketRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Raise a ticket",
    description=(
        "The ticket opens at medium priority with status `open`, and is "
        "given the next serial for the current year, e.g. `TKT-2026-000001`."
    ),
)
async def create_ticket(
    db: DbSession, user: CurrentUser, payload: TicketCreate
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).create(payload, actor=user)
    return created_response(
        data=TicketRead.from_model(ticket), message="Ticket created"
    )


@router.get(
    "/tickets/by-no/{ticket_no}",
    response_model=APIResponse[TicketRead],
    summary="Get a ticket by its reference",
)
async def get_ticket_by_no(
    db: DbSession, user: CurrentUser, ticket_no: str
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).get_by_ticket_no(ticket_no, actor=user)
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket fetched"
    )


@router.get(
    "/tickets/{ticket_id}",
    response_model=APIResponse[TicketDetail],
    summary="Get a ticket with its thread and timeline",
    description=(
        "Internal notes are included only for callers holding "
        "`ticket.internal_note`; every other caller gets the thread without "
        "them."
    ),
)
async def get_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[TicketDetail]:
    detail = await SupportTicketService(db).get_detail(ticket_id, actor=user)
    return success_response(
        data=TicketDetail(
            ticket=TicketRead.from_model(detail["ticket"]),
            messages=[MessageRead.model_validate(m) for m in detail["messages"]],
            attachments=[
                AttachmentRead.model_validate(a) for a in detail["attachments"]
            ],
            activities=[ActivityRead.model_validate(a) for a in detail["activities"]],
            status_history=[
                StatusHistoryRead.model_validate(s) for s in detail["status_history"]
            ],
            assignments=[
                AssignmentRead.model_validate(a) for a in detail["assignments"]
            ],
            feedback=(
                FeedbackRead.model_validate(detail["feedback"])
                if detail["feedback"] is not None
                else None
            ),
        ),
        message="Ticket fetched",
    )


@router.patch(
    "/tickets/{ticket_id}",
    response_model=APIResponse[TicketRead],
    summary="Edit a ticket's subject, description or category",
)
async def update_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: TicketUpdate
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).update(ticket_id, payload, actor=user)
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket updated"
    )


@router.get(
    "/tickets/{ticket_id}/messages",
    response_model=APIResponse[list[MessageRead]],
    summary="Read a ticket's conversation",
)
async def list_messages(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[list[MessageRead]]:
    messages = await SupportTicketService(db).list_messages(ticket_id, actor=user)
    return success_response(
        data=[MessageRead.model_validate(message) for message in messages],
        message="Messages fetched",
    )


@router.post(
    "/tickets/{ticket_id}/reply",
    response_model=APIResponse[MessageRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_reply()],
    summary="Reply to a ticket",
    description=(
        "Updates `last_reply_at`, increments `total_replies`, and moves the "
        "ticket to whichever side is now being waited on. A student replying "
        "to a resolved ticket reopens it."
    ),
)
async def reply_to_ticket(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: MessageCreate
) -> APIResponse[MessageRead]:
    message = await SupportTicketService(db).reply(
        ticket_id, payload.message, actor=user
    )
    return created_response(
        data=MessageRead.model_validate(message), message="Reply added"
    )


@router.post(
    "/tickets/{ticket_id}/close",
    response_model=APIResponse[TicketRead],
    summary="Close a ticket",
    description=(
        "Open to the student who raised it, the assigned agent, and " "administrators."
    ),
)
async def close_ticket(
    db: DbSession,
    user: CurrentUser,
    ticket_id: TicketId,
    payload: TicketClose | None = None,
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).close(
        ticket_id, actor=user, remarks=payload.remarks if payload else None
    )
    return success_response(data=TicketRead.from_model(ticket), message="Ticket closed")


@router.post(
    "/tickets/{ticket_id}/reopen",
    response_model=APIResponse[TicketRead],
    summary="Reopen a closed ticket",
    description=(
        "Allowed within `support_ticket_reopen_days` of closing, configured "
        "in the settings table."
    ),
)
async def reopen_ticket(
    db: DbSession,
    user: CurrentUser,
    ticket_id: TicketId,
    payload: TicketReopen | None = None,
) -> APIResponse[TicketRead]:
    ticket = await SupportTicketService(db).reopen(
        ticket_id, actor=user, reason=payload.reason if payload else None
    )
    return success_response(
        data=TicketRead.from_model(ticket), message="Ticket reopened"
    )


@router.post(
    "/tickets/{ticket_id}/feedback",
    response_model=APIResponse[FeedbackRead],
    status_code=status.HTTP_201_CREATED,
    summary="Rate a finished ticket",
    description="Once per ticket, by the student who raised it, after it ends.",
)
async def submit_feedback(
    db: DbSession, user: CurrentUser, ticket_id: TicketId, payload: FeedbackCreate
) -> APIResponse[FeedbackRead]:
    feedback = await SupportTicketService(db).submit_feedback(
        ticket_id, payload, actor=user
    )
    return created_response(
        data=FeedbackRead.model_validate(feedback), message="Feedback recorded"
    )


# -- Attachments -----------------------------------------------------------


@router.post(
    "/tickets/{ticket_id}/attachments",
    response_model=APIResponse[AttachmentRead],
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to a ticket",
    description=(
        "The size ceiling, the accepted extensions and the per-ticket count "
        "all come from the settings table."
    ),
)
async def upload_attachment(
    db: DbSession,
    user: CurrentUser,
    ticket_id: TicketId,
    file: Annotated[UploadFile, File(description="The file to attach.")],
    message_id: Annotated[
        uuid.UUID | None,
        Query(description="Attach to this reply rather than the ticket."),
    ] = None,
) -> APIResponse[AttachmentRead]:
    service = SupportAttachmentService(db)
    ticket = await SupportTicketService(db).get(ticket_id, actor=user)
    attachment = await service.upload(ticket, file, actor=user, message_id=message_id)
    return created_response(
        data=AttachmentRead.model_validate(attachment), message="Attachment uploaded"
    )


@router.get(
    "/tickets/{ticket_id}/attachments",
    response_model=APIResponse[list[AttachmentRead]],
    summary="List a ticket's attachments",
)
async def list_attachments(
    db: DbSession, user: CurrentUser, ticket_id: TicketId
) -> APIResponse[list[AttachmentRead]]:
    service = SupportAttachmentService(db)
    await SupportTicketService(db).get(ticket_id, actor=user)
    attachments = await service.repository.list_for_ticket(ticket_id)
    return success_response(
        data=[AttachmentRead.model_validate(item) for item in attachments],
        message="Attachments fetched",
    )


@router.get(
    "/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Download an attachment",
    description=(
        "Served through the API rather than from a public directory, so the "
        "caller's right to the parent ticket is checked on every fetch."
    ),
)
async def download_attachment(
    db: DbSession, user: CurrentUser, attachment_id: AttachmentId
) -> FileResponse:
    attachment, path = await SupportAttachmentService(db).open_for_download(
        attachment_id, actor=user
    )
    return FileResponse(
        path,
        filename=attachment.original_name,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.delete(
    "/attachments/{attachment_id}",
    response_model=APIResponse[None],
    summary="Remove an attachment",
)
async def delete_attachment(
    db: DbSession, user: CurrentUser, attachment_id: AttachmentId
) -> APIResponse[None]:
    await SupportAttachmentService(db).delete(attachment_id, actor=user)
    return success_response(message="Attachment removed")
