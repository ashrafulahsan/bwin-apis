"""The public contact form endpoint.

One route, open to the internet, with no permission dependency - a visitor
who has not signed in is exactly who it is for. That is why it lives in its
own router rather than as an exception inside the guarded administrative one:
a route that must stay public should not sit one line away from routes that
must not be.
"""

from fastapi import APIRouter, BackgroundTasks, status

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import SessionContextDep
from app.modules.inquiries.constants import INQUIRY_SUBMITTED_MESSAGE
from app.modules.inquiries.delivery import (
    default_notifier,
    deliver_inquiry_messages,
)
from app.modules.inquiries.schemas.contact_inquiry import InquiryCreate
from app.modules.inquiries.services.contact_inquiry import ContactInquiryService
from app.shared.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/contact-inquiries", tags=["Contact Inquiries"])


@router.post(
    "",
    response_model=APIResponse[None],
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact inquiry",
    description=(
        "Records a submission from the website contact form.\n\n"
        "**Validation.** Name, email, phone and `interested_in` are all "
        "required; the message is not. Text fields are trimmed, and a field "
        "of nothing but spaces is rejected rather than stored blank. The "
        "phone number is normalized to E.164, so `01712-345678` is stored "
        "as `+8801712345678`.\n\n"
        "**The reply never varies.** The same sentence comes back whether "
        "the inquiry was stored or recognised as a repeat of one submitted "
        "moments earlier. A public form that answered differently for known "
        "addresses would be a way to test which addresses are already in "
        "the database.\n\n"
        "**Rate limited** per originating address. Submitting far faster "
        "than a person could returns `429`."
    ),
    responses={
        201: {"description": "The inquiry was received."},
        422: {"description": "A field is missing, blank, or badly formed."},
        429: {"description": "Too many submissions from this address."},
    },
)
async def submit_inquiry(
    db: DbSession,
    payload: InquiryCreate,
    context: SessionContextDep,
    background: BackgroundTasks,
) -> APIResponse[None]:
    service = ContactInquiryService(db)

    inquiry = await service.submit(
        payload,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )

    # Queued rather than awaited: the visitor should not be kept waiting on a
    # mail server, and a mail failure must not fail a submission that has
    # already been committed.
    #
    # The task reads `inquiry` after the request's session has closed. That is
    # safe only because the session factory sets `expire_on_commit=False`, so
    # the attributes loaded by the INSERT are still populated on the detached
    # instance - under the default, every read in there would expire and
    # attempt lazy IO with no session to do it on.
    recipient, acknowledge = await service.notification_settings()
    background.add_task(
        deliver_inquiry_messages,
        inquiry,
        notifier=default_notifier,
        recipient=recipient,
        acknowledge=acknowledge,
    )

    return success_response(message=INQUIRY_SUBMITTED_MESSAGE)
