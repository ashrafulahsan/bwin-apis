"""Administrative endpoints for managing contact inquiries.

Guarded in full at the router: `can_view()` is a dependency of the whole
prefix, so a route added here later is protected whether or not its author
remembers to say so. The stronger verbs add their own on top.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.core.constants import SortOrder
from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.inquiries.constants import InquiryStatus, InterestedIn
from app.modules.inquiries.permissions import can_delete, can_update, can_view
from app.modules.inquiries.schemas.contact_inquiry import (
    InquiryRead,
    InquiryStatistics,
    InquiryStatusUpdate,
    InquirySummary,
    InquiryUpdate,
)
from app.modules.inquiries.services.contact_inquiry import ContactInquiryService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/admin/contact-inquiries",
    tags=["Contact Inquiries - Admin"],
    dependencies=[can_view()],
)

InquiryId = Annotated[uuid.UUID, Path(description="Inquiry identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[InquirySummary]],
    summary="List contact inquiries",
    description=(
        "Newest first by default. Search matches name, email or phone; the "
        "filters narrow by status, interest, read state and date range.\n\n"
        "Internal notes are not included in a listing - use the detail "
        "endpoint for one inquiry."
    ),
)
async def list_inquiries(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    inquiry_status: Annotated[
        InquiryStatus | None, Query(alias="status", description="Handling state.")
    ] = None,
    interested_in: Annotated[InterestedIn | None, Query()] = None,
    is_read: Annotated[bool | None, Query()] = None,
    open_only: Annotated[
        bool, Query(description="Exclude converted, closed and spam.")
    ] = False,
    date_from: Annotated[
        datetime | None, Query(description="Submitted on or after this moment.")
    ] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[Page[InquirySummary]]:
    items, total = await ContactInquiryService(db).list_inquiries(
        pagination,
        search=search.search,
        status=inquiry_status,
        interested_in=interested_in,
        is_read=is_read,
        open_only=open_only,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order or SortOrder.DESC,
    )
    return paginated_response(
        [InquirySummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Inquiries fetched",
    )


@router.get(
    "/statistics",
    response_model=APIResponse[InquiryStatistics],
    summary="Inquiry dashboard counts",
)
async def inquiry_statistics(db: DbSession) -> APIResponse[InquiryStatistics]:
    stats = await ContactInquiryService(db).statistics()
    return success_response(data=stats, message="Statistics fetched")


@router.get(
    "/{inquiry_id}",
    response_model=APIResponse[InquiryRead],
    summary="Get one inquiry",
    description=(
        "Opening an inquiry marks it read and stamps `read_at` and "
        "`read_by` - the first time anyone opens it. Later views leave "
        "those alone but are still written to the activity log, because "
        "who looked at a member of the public's contact details is worth "
        "being able to answer."
    ),
)
async def get_inquiry(
    db: DbSession, user: CurrentUser, inquiry_id: InquiryId
) -> APIResponse[InquiryRead]:
    inquiry = await ContactInquiryService(db).get_and_mark_read(inquiry_id, actor=user)
    return success_response(
        data=InquiryRead.from_model(inquiry), message="Inquiry fetched"
    )


@router.patch(
    "/{inquiry_id}/status",
    response_model=APIResponse[InquiryRead],
    dependencies=[can_update()],
    summary="Update an inquiry's status",
    description=(
        "Moves the inquiry along and optionally replaces the internal "
        "note.\n\n"
        "Omit `notes` to leave the existing note untouched; send it as "
        "`null` to clear it. The previous and new values of everything "
        "that changed are written to the activity log."
    ),
)
async def update_status(
    db: DbSession,
    user: CurrentUser,
    inquiry_id: InquiryId,
    payload: InquiryStatusUpdate,
) -> APIResponse[InquiryRead]:
    inquiry = await ContactInquiryService(db).change_status(
        inquiry_id, payload, actor=user
    )
    return success_response(
        data=InquiryRead.from_model(inquiry), message="Status updated"
    )


@router.patch(
    "/{inquiry_id}",
    response_model=APIResponse[InquiryRead],
    dependencies=[can_update()],
    summary="Correct an inquiry's details",
    description=(
        "For fixing what a visitor mistyped, after speaking to them. The "
        "phone number is normalized the same way the public form does it."
    ),
)
async def update_inquiry(
    db: DbSession, user: CurrentUser, inquiry_id: InquiryId, payload: InquiryUpdate
) -> APIResponse[InquiryRead]:
    inquiry = await ContactInquiryService(db).update(inquiry_id, payload, actor=user)
    return success_response(
        data=InquiryRead.from_model(inquiry), message="Inquiry updated"
    )


@router.post(
    "/{inquiry_id}/unread",
    response_model=APIResponse[InquiryRead],
    dependencies=[can_update()],
    summary="Mark an inquiry unread",
)
async def mark_unread(
    db: DbSession, user: CurrentUser, inquiry_id: InquiryId
) -> APIResponse[InquiryRead]:
    inquiry = await ContactInquiryService(db).mark_unread(inquiry_id, actor=user)
    return success_response(
        data=InquiryRead.from_model(inquiry), message="Inquiry marked unread"
    )


@router.delete(
    "/{inquiry_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete an inquiry",
    description=(
        "Soft delete only. The row stays so the deletion itself is "
        "auditable, and stops being returned by every read."
    ),
)
async def delete_inquiry(
    db: DbSession, user: CurrentUser, inquiry_id: InquiryId
) -> APIResponse[None]:
    await ContactInquiryService(db).delete(inquiry_id, actor=user)
    return deleted_response("Inquiry deleted")


@router.post(
    "/{inquiry_id}/restore",
    response_model=APIResponse[InquiryRead],
    dependencies=[can_delete()],
    summary="Restore a deleted inquiry",
)
async def restore_inquiry(
    db: DbSession, user: CurrentUser, inquiry_id: InquiryId
) -> APIResponse[InquiryRead]:
    inquiry = await ContactInquiryService(db).restore(inquiry_id, actor=user)
    return success_response(
        data=InquiryRead.from_model(inquiry), message="Inquiry restored"
    )
