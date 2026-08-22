"""Administrative subscription endpoints.

Guarded in full: `can_view()` on the router, and the write permission on each
route that writes. The public half of the module lives in `newsletter.py`,
behind its own prefix, precisely so that nothing here has to be an exception.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.subscriptions.constants import SubscriptionStatus
from app.modules.subscriptions.permissions import (
    can_create,
    can_delete,
    can_update,
    can_view,
)
from app.modules.subscriptions.schemas.subscription import (
    AdminUnsubscribe,
    SubscriptionCreate,
    SubscriptionRead,
    SubscriptionStats,
    SubscriptionSummary,
    SubscriptionUpdate,
)
from app.modules.subscriptions.services.subscription import SubscriptionService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/subscriptions", tags=["Subscriptions"], dependencies=[can_view()]
)
SubscriptionId = Annotated[uuid.UUID, Path(description="Subscription identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[SubscriptionSummary]],
    summary="List subscriptions",
    description=(
        "Every filter is optional and they combine. `mailable_only=true` is "
        "the one to reach for before a send: it returns confirmed addresses "
        "only, which is not the same as every row."
    ),
)
async def list_subscriptions(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    subscription_status: Annotated[
        SubscriptionStatus | None,
        Query(alias="status", description="Only addresses in this state."),
    ] = None,
    source: Annotated[
        str | None, Query(description="Only signups from this source.")
    ] = None,
    mailable_only: Annotated[
        bool, Query(description="Only addresses a campaign may be sent to.")
    ] = False,
) -> APIResponse[Page[SubscriptionSummary]]:
    items, total = await SubscriptionService(db).list_subscriptions(
        pagination,
        search=search.search,
        status=subscription_status,
        source=source,
        mailable_only=mailable_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )
    return paginated_response(
        [SubscriptionSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Subscriptions fetched",
    )


@router.get(
    "/stats",
    response_model=APIResponse[SubscriptionStats],
    summary="List size by status",
    description=(
        "Counted in the database rather than by loading the list. `mailable` "
        "is the number a campaign would actually reach."
    ),
)
async def subscription_stats(db: DbSession) -> APIResponse[SubscriptionStats]:
    counts = await SubscriptionService(db).stats()

    return success_response(
        data=SubscriptionStats.from_counts(counts), message="Statistics fetched"
    )


@router.get(
    "/by-email/{email}",
    response_model=APIResponse[SubscriptionRead],
    summary="Get a subscription by address",
)
async def get_subscription_by_email(
    db: DbSession, email: str
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).get_by_email(email)

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription fetched",
    )


@router.get(
    "/{subscription_id}",
    response_model=APIResponse[SubscriptionRead],
    summary="Get a subscription",
)
async def get_subscription(
    db: DbSession, subscription_id: SubscriptionId
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).get(subscription_id)

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription fetched",
    )


@router.post(
    "",
    response_model=APIResponse[SubscriptionRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Add a subscription",
    description=(
        "Adds an address directly, already confirmed. No confirmation email "
        "is sent: an administrator entering an address is asserting that it "
        "asked to be here, and the audit trail records who asserted it."
    ),
)
async def create_subscription(
    db: DbSession, user: CurrentUser, payload: SubscriptionCreate
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).create(payload, actor_id=user.id)

    return created_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription created",
    )


@router.patch(
    "/{subscription_id}",
    response_model=APIResponse[SubscriptionRead],
    dependencies=[can_update()],
    summary="Update a subscription",
    description=(
        "Corrects the address, name or source. Status is not settable here - "
        "joining and leaving have their own endpoints so that every move is "
        "attributable."
    ),
)
async def update_subscription(
    db: DbSession,
    user: CurrentUser,
    subscription_id: SubscriptionId,
    payload: SubscriptionUpdate,
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).update(
        subscription_id, payload, actor_id=user.id
    )

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription updated",
    )


@router.post(
    "/{subscription_id}/subscribe",
    response_model=APIResponse[SubscriptionRead],
    dependencies=[can_update()],
    summary="Confirm a subscription by hand",
    description=(
        "For the address that asked in person or by reply, and for a pending "
        "signup whose confirmation email has not reached it."
    ),
)
async def subscribe_by_hand(
    db: DbSession, user: CurrentUser, subscription_id: SubscriptionId
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).mark_subscribed(
        subscription_id, actor_id=user.id
    )

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription confirmed",
    )


@router.post(
    "/{subscription_id}/unsubscribe",
    response_model=APIResponse[SubscriptionRead],
    dependencies=[can_update()],
    summary="Unsubscribe an address on request",
    description=(
        'For somebody who replied "take me off this" rather than clicking '
        "the link. The row is kept, set to unsubscribed - deleting it would "
        "let the next import put the address straight back."
    ),
)
async def unsubscribe_by_hand(
    db: DbSession,
    user: CurrentUser,
    subscription_id: SubscriptionId,
    payload: AdminUnsubscribe,
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).mark_unsubscribed(
        subscription_id, reason=payload.reason, actor_id=user.id
    )

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Unsubscribed",
    )


@router.post(
    "/{subscription_id}/bounced",
    response_model=APIResponse[SubscriptionRead],
    dependencies=[can_update()],
    summary="Mark an address as bouncing",
    description=(
        "Keeps a dead address out of every send. Continuing to mail one is "
        "what costs the live addresses their deliverability."
    ),
)
async def mark_bounced(
    db: DbSession, user: CurrentUser, subscription_id: SubscriptionId
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).mark_bounced(
        subscription_id, actor_id=user.id
    )

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Marked as bouncing",
    )


@router.delete(
    "/{subscription_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete a subscription",
    description=(
        "Soft delete, for a row that should not have been created. This is "
        "not how somebody leaves the list - use `/unsubscribe` for that, "
        "which keeps the record of their request."
    ),
)
async def delete_subscription(
    db: DbSession, subscription_id: SubscriptionId
) -> APIResponse[None]:
    await SubscriptionService(db).delete(subscription_id)

    return deleted_response("Subscription deleted")


@router.post(
    "/{subscription_id}/restore",
    response_model=APIResponse[SubscriptionRead],
    dependencies=[can_delete()],
    summary="Restore a subscription",
)
async def restore_subscription(
    db: DbSession, subscription_id: SubscriptionId
) -> APIResponse[SubscriptionRead]:
    subscription = await SubscriptionService(db).restore(subscription_id)

    return success_response(
        data=SubscriptionRead.model_validate(subscription),
        message="Subscription restored",
    )
