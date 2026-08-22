"""Tests for the newsletter subscriptions module."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityLog,
    ActivityModule,
)
from app.modules.subscriptions.constants import (
    SUBSCRIPTION_CONFIRMATION_TTL,
    SubscriptionStatus,
)
from app.modules.subscriptions.models.subscription import Subscription
from app.modules.subscriptions.schemas.subscription import (
    SubscribeRequest,
    SubscriptionCreate,
    SubscriptionStats,
    SubscriptionUpdate,
)
from app.modules.subscriptions.services.subscription import SubscriptionService
from app.modules.subscriptions.tokens import (
    build_unsubscribe_token,
    parse_unsubscribe_token,
)
from app.modules.users.models.user import User
from app.shared.utils.dates import utc_now


class CapturingSender:
    """Keeps the confirmation links instead of sending them.

    The service hands the raw token to the sender and keeps only its digest,
    which is the whole point of the design - so the sender is also the only
    place a test can get a usable link from. That mirrors reality: whatever
    composes the email is what holds the token.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, email: str, link: str) -> None:
        self.sent.append((email, link))

    @property
    def last_token(self) -> str:
        return self.sent[-1][1].rsplit("token=", 1)[1]


@pytest.fixture
async def sender() -> CapturingSender:
    return CapturingSender()


@pytest.fixture
async def subscriptions(
    session: AsyncSession, sender: CapturingSender
) -> AsyncIterator[SubscriptionService]:
    await session.execute(delete(Subscription))
    await session.execute(delete(User))
    await session.commit()

    yield SubscriptionService(session, sender=sender)

    await session.execute(delete(Subscription))
    await session.execute(delete(User))
    await session.commit()


def signup(email: str = "reader@example.com") -> SubscribeRequest:
    return SubscribeRequest(email=email, name="Reader", source="footer")


# -- The public process -------------------------------------------------


async def test_signing_up_does_not_put_the_address_on_the_list(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    """The point of confirmed opt-in: pending is not subscribed."""
    await subscriptions.subscribe(signup())

    stored = await subscriptions.get_by_email("reader@example.com")
    assert stored.status == SubscriptionStatus.PENDING
    assert stored.is_mailable is False
    assert stored.confirmed_at is None
    assert len(sender.sent) == 1

    activity = (
        (
            await subscriptions.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(stored.id))
            )
        )
        .scalars()
        .all()
    )
    assert activity[-1].module == ActivityModule.SUBSCRIPTIONS
    assert activity[-1].action == ActivityAction.SUBSCRIBE
    assert activity[-1].entity_type == "Subscription"


async def test_confirming_puts_the_address_on_the_list(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    await subscriptions.subscribe(signup())

    confirmed = await subscriptions.confirm(sender.last_token)

    assert confirmed.status == SubscriptionStatus.SUBSCRIBED
    assert confirmed.is_mailable is True
    assert confirmed.confirmed_at is not None
    # Spent: the digest is gone, so the same link cannot be used again.
    assert confirmed.confirmation_token_hash is None


async def test_a_confirmation_link_works_only_once(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    await subscriptions.subscribe(signup())
    token = sender.last_token
    await subscriptions.confirm(token)

    with pytest.raises(NotFoundException):
        await subscriptions.confirm(token)


async def test_an_expired_confirmation_link_is_refused(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    await subscriptions.subscribe(signup())
    stored = await subscriptions.get_by_email("reader@example.com")
    await subscriptions.repository.update(
        stored, confirmation_expires_at=utc_now() - SUBSCRIPTION_CONFIRMATION_TTL
    )
    await subscriptions.session.commit()

    with pytest.raises(BadRequestException):
        await subscriptions.confirm(sender.last_token)


async def test_the_email_is_normalized(subscriptions: SubscriptionService) -> None:
    await subscriptions.subscribe(signup("Reader@Example.COM"))

    stored = await subscriptions.get_by_email("reader@example.com")
    assert stored.email == "reader@example.com"


async def test_signing_up_twice_does_not_create_a_second_row(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    """The address is unique, and the second attempt is inside the cooldown."""
    await subscriptions.subscribe(signup())
    await subscriptions.subscribe(signup())

    _, total = await subscriptions.list_subscriptions(PaginationParams())
    assert total == 1
    # The cooldown held, so no second link went out to flood the inbox.
    assert len(sender.sent) == 1


async def test_signing_up_an_address_already_on_the_list_sends_nothing(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    """Re-confirming a subscriber would tell the sender they are subscribed."""
    await subscriptions.subscribe(signup())
    await subscriptions.confirm(sender.last_token)

    await subscriptions.subscribe(signup())

    assert len(sender.sent) == 1
    stored = await subscriptions.get_by_email("reader@example.com")
    assert stored.status == SubscriptionStatus.SUBSCRIBED


async def test_unsubscribing_keeps_the_row(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    """Deleting it would let the next import put the address straight back."""
    await subscriptions.subscribe(signup())
    subscription = await subscriptions.confirm(sender.last_token)

    left = await subscriptions.unsubscribe(
        build_unsubscribe_token(subscription.id), reason="Too many emails"
    )

    assert left.status == SubscriptionStatus.UNSUBSCRIBED
    assert left.is_mailable is False
    assert left.unsubscribed_at is not None
    assert left.unsubscribe_reason == "Too many emails"
    assert await subscriptions.get(subscription.id) is not None


async def test_unsubscribing_twice_is_not_an_error(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    """The reader asked to be off the list; a second click is not a conflict."""
    await subscriptions.subscribe(signup())
    subscription = await subscriptions.confirm(sender.last_token)
    token = build_unsubscribe_token(subscription.id)

    await subscriptions.unsubscribe(token)
    again = await subscriptions.unsubscribe(token)

    assert again.status == SubscriptionStatus.UNSUBSCRIBED


async def test_someone_who_left_can_come_back(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    await subscriptions.subscribe(signup())
    subscription = await subscriptions.confirm(sender.last_token)
    await subscriptions.unsubscribe(build_unsubscribe_token(subscription.id))

    # Past the cooldown, so the resend is allowed.
    await subscriptions.repository.update(
        await subscriptions.get(subscription.id), confirmation_sent_at=None
    )
    await subscriptions.session.commit()
    await subscriptions.subscribe(signup())

    returning = await subscriptions.get_by_email("reader@example.com")
    # Pending, not subscribed: coming back still has to be confirmed.
    assert returning.status == SubscriptionStatus.PENDING
    assert returning.unsubscribed_at is None

    confirmed = await subscriptions.confirm(sender.last_token)
    assert confirmed.status == SubscriptionStatus.SUBSCRIBED


async def test_signing_up_revives_a_deleted_row(
    subscriptions: SubscriptionService,
) -> None:
    """`email` is unique table-wide, so a deleted row still owns the address."""
    await subscriptions.subscribe(signup())
    stored = await subscriptions.get_by_email("reader@example.com")
    await subscriptions.delete(stored.id)

    await subscriptions.repository.update(
        await subscriptions.repository.get(stored.id, include_deleted=True),
        confirmation_sent_at=None,
    )
    await subscriptions.session.commit()
    await subscriptions.subscribe(signup())

    revived = await subscriptions.get_by_email("reader@example.com")
    assert revived.id == stored.id
    assert revived.deleted_at is None
    assert revived.status == SubscriptionStatus.PENDING


# -- Unsubscribe tokens -------------------------------------------------


async def test_an_unsubscribe_token_round_trips() -> None:
    subscription_id = uuid.uuid4()

    token = build_unsubscribe_token(subscription_id)

    assert parse_unsubscribe_token(token) == subscription_id


async def test_a_tampered_unsubscribe_token_is_rejected() -> None:
    """The id is signed, so swapping it in does not unsubscribe a stranger."""
    token = build_unsubscribe_token(uuid.uuid4())
    _, _, signature = token.partition(".")

    assert parse_unsubscribe_token(f"{uuid.uuid4()}.{signature}") is None
    assert parse_unsubscribe_token("not-a-token") is None
    assert parse_unsubscribe_token(f"{uuid.uuid4()}.deadbeef") is None


async def test_an_unknown_unsubscribe_token_is_refused(
    subscriptions: SubscriptionService,
) -> None:
    with pytest.raises(NotFoundException):
        await subscriptions.unsubscribe(build_unsubscribe_token(uuid.uuid4()))


# -- Administration -----------------------------------------------------


async def test_an_admin_added_address_is_already_confirmed(
    subscriptions: SubscriptionService, sender: CapturingSender
) -> None:
    created = await subscriptions.create(
        SubscriptionCreate(email="known@example.com", name="Known Contact")
    )

    assert created.status == SubscriptionStatus.SUBSCRIBED
    assert created.confirmed_at is not None
    assert created.source == "admin"
    # Nobody to confirm to: no link is sent.
    assert sender.sent == []


async def test_adding_the_same_address_twice_conflicts(
    subscriptions: SubscriptionService,
) -> None:
    await subscriptions.create(SubscriptionCreate(email="known@example.com"))

    with pytest.raises(ConflictException):
        await subscriptions.create(SubscriptionCreate(email="Known@Example.com"))


async def test_admin_can_confirm_and_unsubscribe_by_hand(
    subscriptions: SubscriptionService,
) -> None:
    await subscriptions.subscribe(signup())
    stored = await subscriptions.get_by_email("reader@example.com")

    confirmed = await subscriptions.mark_subscribed(stored.id)
    assert confirmed.status == SubscriptionStatus.SUBSCRIBED

    with pytest.raises(ConflictException):
        await subscriptions.mark_subscribed(stored.id)

    left = await subscriptions.mark_unsubscribed(stored.id, reason="Asked by reply")
    assert left.status == SubscriptionStatus.UNSUBSCRIBED
    assert left.unsubscribe_reason == "Asked by reply"

    with pytest.raises(ConflictException):
        await subscriptions.mark_unsubscribed(stored.id)


async def test_marking_an_address_as_bouncing(
    subscriptions: SubscriptionService,
) -> None:
    created = await subscriptions.create(SubscriptionCreate(email="dead@example.com"))

    bounced = await subscriptions.mark_bounced(created.id)

    assert bounced.status == SubscriptionStatus.BOUNCED
    assert bounced.is_mailable is False


async def test_update_corrects_the_address(
    subscriptions: SubscriptionService,
) -> None:
    created = await subscriptions.create(SubscriptionCreate(email="typo@example.com"))

    updated = await subscriptions.update(
        created.id, SubscriptionUpdate(email="Fixed@Example.com", name="Fixed")
    )

    assert updated.email == "fixed@example.com"
    assert updated.name == "Fixed"


async def test_update_refuses_an_address_already_on_the_list(
    subscriptions: SubscriptionService,
) -> None:
    await subscriptions.create(SubscriptionCreate(email="first@example.com"))
    second = await subscriptions.create(SubscriptionCreate(email="second@example.com"))

    with pytest.raises(ConflictException):
        await subscriptions.update(
            second.id, SubscriptionUpdate(email="first@example.com")
        )


async def test_search_and_filters(subscriptions: SubscriptionService) -> None:
    await subscriptions.create(
        SubscriptionCreate(email="alice@example.com", name="Alice", source="admin")
    )
    bounced = await subscriptions.create(
        SubscriptionCreate(email="bob@example.com", source="import")
    )
    await subscriptions.mark_bounced(bounced.id)
    await subscriptions.subscribe(signup("carol@example.com"))

    found, total = await subscriptions.list_subscriptions(
        PaginationParams(), search="alice"
    )
    assert total == 1
    assert found[0].email == "alice@example.com"

    _, pending = await subscriptions.list_subscriptions(
        PaginationParams(), status=SubscriptionStatus.PENDING
    )
    assert pending == 1

    _, by_source = await subscriptions.list_subscriptions(
        PaginationParams(), source="admin"
    )
    assert by_source == 1

    mailable, mailable_total = await subscriptions.list_subscriptions(
        PaginationParams(), mailable_only=True
    )
    # Alice only: the bounced address and the unconfirmed one are not on the list.
    assert mailable_total == 1
    assert mailable[0].email == "alice@example.com"


async def test_stats_count_the_list_by_status(
    subscriptions: SubscriptionService,
) -> None:
    await subscriptions.create(SubscriptionCreate(email="alice@example.com"))
    await subscriptions.subscribe(signup("carol@example.com"))

    stats = SubscriptionStats.from_counts(await subscriptions.stats())

    assert stats.total == 2
    assert stats.subscribed == 1
    assert stats.pending == 1
    assert stats.mailable == 1
    assert stats.unsubscribed == 0


async def test_delete_and_restore(subscriptions: SubscriptionService) -> None:
    created = await subscriptions.create(SubscriptionCreate(email="gone@example.com"))

    await subscriptions.delete(created.id)
    with pytest.raises(NotFoundException):
        await subscriptions.get(created.id)

    restored = await subscriptions.restore(created.id)
    assert restored.deleted_at is None


async def test_the_unsubscribe_link_points_at_the_frontend(
    subscriptions: SubscriptionService,
) -> None:
    created = await subscriptions.create(SubscriptionCreate(email="reader@example.com"))

    link = await subscriptions.unsubscribe_link(created)

    assert "token=" in link
    assert parse_unsubscribe_token(link.rsplit("token=", 1)[1]) == created.id
