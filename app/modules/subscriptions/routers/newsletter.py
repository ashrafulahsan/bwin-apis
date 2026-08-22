"""Public newsletter endpoints: subscribe, confirm, unsubscribe.

Open to the internet, with no permission dependency - a visitor who has not
signed in is exactly who these are for. That is why they are a separate router
from the administrative one, which is guarded in full at its own prefix.

The three of them are the subscription process end to end: a form posts to
`/subscribe`, the link in the resulting email lands on `/confirm`, and the
link in the footer of every later message lands on `/unsubscribe`.
"""

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import SessionContextDep
from app.modules.subscriptions.constants import SUBSCRIPTION_REQUESTED_MESSAGE
from app.modules.subscriptions.schemas.subscription import (
    ConfirmRequest,
    SubscribeRequest,
    SubscriptionSummary,
    UnsubscribeRequest,
)
from app.modules.subscriptions.services.subscription import SubscriptionService
from app.shared.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/newsletter", tags=["Newsletter"])


@router.post(
    "/subscribe",
    response_model=APIResponse[None],
    summary="Sign up for the newsletter",
    description=(
        "Records the request and sends a confirmation link. The address is "
        "**not** on the list until that link is followed.\n\n"
        "The reply is the same whether the address is new, already "
        "subscribed, still pending, or asking again within the resend "
        "cooldown. That is deliberate: a form open to the internet that "
        "answered differently for known addresses would be a way to test "
        "which addresses are on the list."
    ),
)
async def subscribe(
    db: DbSession, payload: SubscribeRequest, context: SessionContextDep
) -> APIResponse[None]:
    await SubscriptionService(db).subscribe(payload, ip_address=context.ip_address)

    return success_response(message=SUBSCRIPTION_REQUESTED_MESSAGE)


@router.post(
    "/confirm",
    response_model=APIResponse[SubscriptionSummary],
    summary="Confirm a subscription",
    description=(
        "Spends the token from a confirmation link and puts the address on "
        "the list. The link works once, and expires if it is left too long."
    ),
)
async def confirm(
    db: DbSession, payload: ConfirmRequest
) -> APIResponse[SubscriptionSummary]:
    subscription = await SubscriptionService(db).confirm(payload.token)

    return success_response(
        data=SubscriptionSummary.model_validate(subscription),
        message="Subscription confirmed",
    )


@router.post(
    "/unsubscribe",
    response_model=APIResponse[SubscriptionSummary],
    summary="Unsubscribe from the newsletter",
    description=(
        "Honours the token from a message footer. The token does not expire, "
        "and unsubscribing twice succeeds quietly rather than erroring - the "
        "reader asked to be off the list, so being off the list is the right "
        "answer to a second click."
    ),
)
async def unsubscribe(
    db: DbSession, payload: UnsubscribeRequest
) -> APIResponse[SubscriptionSummary]:
    subscription = await SubscriptionService(db).unsubscribe(
        payload.token, reason=payload.reason
    )

    return success_response(
        data=SubscriptionSummary.model_validate(subscription),
        message="Unsubscribed",
    )
