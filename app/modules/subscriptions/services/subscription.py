"""Business logic for newsletter subscriptions.

Two things govern the shape of this file.

**The public half must not leak the list.** `subscribe` returns nothing in
every case - new address, known address, address in its cooldown - because the
caller replies with one fixed message either way. If the response varied, the
signup form would be a way to ask "is this person subscribed?" about anybody.
The refusals are logged instead, where the person asking cannot see them.

**Joining and leaving are transitions, not a settable column.** Nothing here
lets a caller assign `status` directly. Every move between states goes through
a method that records who did it and when, which is what makes "we never
mailed anyone who did not ask" a claim the audit trail can support.
"""

import logging
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.core.security import token_fingerprint
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.settings.constants import SettingKey
from app.modules.settings.services.setting import SettingService
from app.modules.subscriptions.constants import (
    SUBSCRIPTION_CONFIRMATION_COOLDOWN,
    SUBSCRIPTION_CONFIRMATION_TTL,
    SUBSCRIPTION_SEARCH_FIELDS,
    SUBSCRIPTION_TOKEN_BYTES,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.modules.subscriptions.delivery import ConfirmationLinkSender, default_sender
from app.modules.subscriptions.models.subscription import Subscription
from app.modules.subscriptions.repositories.subscription import SubscriptionRepository
from app.modules.subscriptions.schemas.subscription import (
    SubscribeRequest,
    SubscriptionCreate,
    SubscriptionUpdate,
)
from app.modules.subscriptions.tokens import (
    build_unsubscribe_token,
    parse_unsubscribe_token,
)
from app.modules.users.constants import normalize_email
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Runs the subscription process and the administration of the list.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(
        self, session: AsyncSession, sender: ConfirmationLinkSender | None = None
    ) -> None:
        self.session = session
        self.repository = SubscriptionRepository(session)
        self.settings = SettingService(session)
        self.activity = ActivityLogService(session, ActivityModule.SUBSCRIPTIONS)
        self.sender = sender or default_sender

    # -- The public process ---------------------------------------------

    async def subscribe(
        self, payload: SubscribeRequest, *, ip_address: str | None = None
    ) -> None:
        """Take a signup from the public form.

        Returns nothing in every case, on purpose - see the module docstring.
        An address that is already confirmed is left alone and sent nothing:
        re-confirming somebody who is already on the list only tells the
        sender of the form that they are on it.
        """
        email = normalize_email(str(payload.email))
        # Deleted rows included: `email` is unique table-wide, so a removed
        # row still owns the address and has to be revived rather than
        # inserted alongside.
        existing = await self.repository.get_by_email(email, include_deleted=True)

        if existing is None:
            await self._start_new(email, payload, ip_address=ip_address)
            return

        if existing.deleted_at is None and existing.is_confirmed:
            logger.info("Signup for an address already on the list")
            return

        await self._resume(existing, payload, ip_address=ip_address)

    async def _start_new(
        self,
        email: str,
        payload: SubscribeRequest,
        *,
        ip_address: str | None,
    ) -> None:
        """First time this address has been seen."""
        token = self._new_token()
        subscription = await self.repository.create(
            email=email,
            name=payload.name,
            source=payload.source or SubscriptionSource.WEBSITE.value,
            status=SubscriptionStatus.PENDING.value,
            confirmation_token_hash=token_fingerprint(token),
            confirmation_expires_at=utc_now() + SUBSCRIPTION_CONFIRMATION_TTL,
            confirmation_sent_at=utc_now(),
            signup_ip=ip_address,
        )

        await self.activity.record(
            ActivityAction.SUBSCRIBE,
            entity=subscription,
            description=f"{email} asked to join the newsletter",
            new_values=snapshot(subscription),
        )
        await self.session.commit()
        await self._deliver(subscription, token)

    async def _resume(
        self,
        subscription: Subscription,
        payload: SubscribeRequest,
        *,
        ip_address: str | None,
    ) -> None:
        """A known address asking again.

        Covers three cases with one path: a pending signup whose link was
        lost, somebody who unsubscribed and has changed their mind, and a row
        an administrator removed. All three end up pending with a fresh link,
        because all three still have to prove the address wants this.
        """
        if not self._may_resend(subscription):
            return

        token = self._new_token()
        changes: dict[str, object] = {
            "status": SubscriptionStatus.PENDING.value,
            "confirmation_token_hash": token_fingerprint(token),
            "confirmation_expires_at": utc_now() + SUBSCRIPTION_CONFIRMATION_TTL,
            "confirmation_sent_at": utc_now(),
            # Leaving is over: clear the record of it so the row does not read
            # as both subscribed and unsubscribed.
            "unsubscribed_at": None,
            "unsubscribe_reason": None,
            "deleted_at": None,
        }
        if payload.name:
            changes["name"] = payload.name
        if ip_address:
            changes["signup_ip"] = ip_address

        updated = await self.repository.update(subscription, **changes)

        await self.activity.record(
            ActivityAction.SUBSCRIBE,
            entity=updated,
            description=f"{updated.email} asked to join the newsletter again",
            new_values={"status": updated.status},
        )
        await self.session.commit()
        await self._deliver(updated, token)

    def _may_resend(self, subscription: Subscription) -> bool:
        """Throttle per address, so this cannot be used to flood an inbox."""
        sent = subscription.confirmation_sent_at
        if sent is not None and utc_now() - sent < SUBSCRIPTION_CONFIRMATION_COOLDOWN:
            logger.info("Newsletter confirmation is in its cooldown")
            return False
        return True

    async def confirm(self, token: str) -> Subscription:
        """Spend a confirmation link and put the address on the list.

        Unlike `subscribe`, this does raise on a bad token. The token *is* the
        secret, so somebody holding one has already proved what the vague
        answer elsewhere exists to protect, and a visitor who followed a stale
        link needs to be told it is stale rather than shown a success page
        that silently did nothing.
        """
        subscription = await self.repository.get_by_confirmation_token(
            token_fingerprint(token)
        )

        if subscription is None:
            raise NotFoundException("That confirmation link")
        if subscription.confirmation_expired:
            raise BadRequestException(
                "That confirmation link has expired. Please sign up again."
            )

        moment = utc_now()
        updated = await self.repository.update(
            subscription,
            status=SubscriptionStatus.SUBSCRIBED.value,
            confirmed_at=moment,
            # Spent: the same link must not work twice.
            confirmation_token_hash=None,
            confirmation_expires_at=None,
        )

        await self.activity.record(
            ActivityAction.VERIFY,
            entity=updated,
            description=f"{updated.email} confirmed their subscription",
            new_values={"status": updated.status, "confirmed_at": moment.isoformat()},
        )
        await self.session.commit()

        logger.info("Newsletter subscription confirmed")
        return updated

    async def unsubscribe(
        self, token: str, *, reason: str | None = None
    ) -> Subscription:
        """Honour an unsubscribe link from a message footer.

        Unsubscribing twice is not an error. The reader clicked the link; the
        outcome they asked for is the outcome they get, and returning a
        conflict for a second click would be pedantry aimed at somebody who is
        already annoyed enough to leave.
        """
        subscription_id = parse_unsubscribe_token(token)
        if subscription_id is None:
            raise NotFoundException("That unsubscribe link")

        # Deleted rows included: an unsubscribe link has to keep working after
        # an administrator has removed the row from their view, or the
        # platform is refusing a request it is obliged to honour.
        subscription = await self.repository.get(subscription_id, include_deleted=True)
        if subscription is None:
            raise NotFoundException("That unsubscribe link")

        if subscription.status == SubscriptionStatus.UNSUBSCRIBED:
            return subscription

        updated = await self._leave(subscription, reason=reason)

        await self.activity.record(
            ActivityAction.UNSUBSCRIBE,
            entity=updated,
            description=f"{updated.email} unsubscribed",
            new_values={"status": updated.status, "unsubscribe_reason": reason},
        )
        await self.session.commit()

        logger.info("Newsletter unsubscribe honoured")
        return updated

    async def _leave(
        self, subscription: Subscription, *, reason: str | None
    ) -> Subscription:
        """The state change shared by the public and administrative paths."""
        return await self.repository.update(
            subscription,
            status=SubscriptionStatus.UNSUBSCRIBED.value,
            unsubscribed_at=utc_now(),
            unsubscribe_reason=reason,
            # Any outstanding confirmation link is void: somebody who has just
            # left must not be able to walk back in through an old email.
            confirmation_token_hash=None,
            confirmation_expires_at=None,
        )

    # -- Delivery -------------------------------------------------------

    async def _deliver(self, subscription: Subscription, token: str) -> None:
        """Send the confirmation link, after the row is safely committed."""
        link = await self._build_link(token)
        await self.sender.send(subscription.email, link)

    async def _build_link(self, token: str) -> str:
        """The URL that goes in the message.

        Points at the frontend rather than at this API: the reader needs a
        page that tells them it worked, and where that page lives is
        configuration, not something to hardcode.
        """
        frontend = await self.settings.value(SettingKey.FRONTEND_URL.value)
        path = await self.settings.value(
            SettingKey.NEWSLETTER_CONFIRM_PATH.value, "/newsletter/confirm"
        )

        if not frontend:
            # Better a bare token in the log than nothing at all, and it is
            # still enough to finish the flow through the API.
            return f"(no frontend_url configured) token={token}"

        return f"{frontend.rstrip('/')}{path or '/newsletter/confirm'}?token={token}"

    async def unsubscribe_link(self, subscription: Subscription) -> str:
        """The unsubscribe URL for one subscriber.

        What a campaign sender puts in the footer of every message. The token
        is derived rather than looked up, so this works for any subscriber at
        any time without the row holding anything worth stealing.
        """
        frontend = await self.settings.value(SettingKey.FRONTEND_URL.value)
        path = await self.settings.value(
            SettingKey.NEWSLETTER_UNSUBSCRIBE_PATH.value, "/newsletter/unsubscribe"
        )
        token = build_unsubscribe_token(subscription.id)

        if not frontend:
            return f"(no frontend_url configured) token={token}"

        return (
            f"{frontend.rstrip('/')}"
            f"{path or '/newsletter/unsubscribe'}?token={token}"
        )

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(SUBSCRIPTION_TOKEN_BYTES)

    # -- Administration: reads ------------------------------------------

    async def get(self, subscription_id: uuid.UUID) -> Subscription:
        return await self.repository.get_or_raise(subscription_id)

    async def get_by_email(self, email: str) -> Subscription:
        subscription = await self.repository.get_by_email(normalize_email(email))
        if subscription is None:
            raise NotFoundException(f"Subscription for '{email}'")
        return subscription

    async def list_subscriptions(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: SubscriptionStatus | None = None,
        source: str | None = None,
        mailable_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Subscription], int]:
        filters = []
        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if source is not None:
            filters.append(Filter.eq("source", source))
        if mailable_only:
            # Who a campaign would actually reach. Expressed in SQL rather
            # than by filtering the page afterwards, which would return short
            # pages and a total that disagrees with them.
            filters.append(Filter.eq("status", SubscriptionStatus.SUBSCRIBED.value))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(SUBSCRIPTION_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def stats(self) -> dict[str, int]:
        return await self.repository.count_by_status()

    # -- Administration: writes -----------------------------------------

    async def create(
        self, payload: SubscriptionCreate, *, actor_id: uuid.UUID | None = None
    ) -> Subscription:
        """Add an address directly.

        Created already confirmed. An administrator typing an address in is
        asserting that it asked to be here - there is nobody to send a
        confirmation link to who is not already expecting to hear from the
        platform - so `confirmed_at` records the assertion and the audit entry
        records who made it.
        """
        email = normalize_email(str(payload.email))
        if await self.repository.email_exists(email):
            raise ConflictException(f"'{email}' is already on the list.")

        moment = utc_now()
        subscription = await self.repository.create(
            email=email,
            name=payload.name,
            source=payload.source or SubscriptionSource.ADMIN.value,
            status=SubscriptionStatus.SUBSCRIBED.value,
            confirmed_at=moment,
            created_by=actor_id,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=subscription,
            description=f"Added {email} to the newsletter",
            new_values=snapshot(subscription),
        )
        await self.session.commit()
        return subscription

    async def update(
        self,
        subscription_id: uuid.UUID,
        payload: SubscriptionUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Subscription:
        subscription = await self.repository.get_or_raise(subscription_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return subscription

        # An explicit `null` on the address reads as "leave this alone" - a
        # client clearing a form field it never edited. The alternative is a
        # 500 from the NOT NULL constraint.
        if changes.get("email") is None:
            changes.pop("email", None)

        if "email" in changes:
            email = normalize_email(str(changes["email"]))
            if await self.repository.email_exists(email, exclude_id=subscription.id):
                raise ConflictException(f"'{email}' is already on the list.")
            changes["email"] = email

        changes["updated_by"] = actor_id

        before = snapshot(subscription, fields=changes.keys())
        updated = await self.repository.update(subscription, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated subscription {updated.email!r}",
                old_values=old_values,
                new_values=new_values,
            )
        await self.session.commit()
        return updated

    async def mark_subscribed(
        self, subscription_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Subscription:
        """Confirm an address by hand.

        For the address that asked in person, at a desk, or by reply - and for
        the pending signup whose confirmation email never arrives while the
        platform has no mail transport.
        """
        subscription = await self.repository.get_or_raise(subscription_id)
        if subscription.is_confirmed:
            raise ConflictException(f"'{subscription.email}' is already subscribed.")

        previous_status = subscription.status
        updated = await self.repository.update(
            subscription,
            status=SubscriptionStatus.SUBSCRIBED.value,
            confirmed_at=subscription.confirmed_at or utc_now(),
            unsubscribed_at=None,
            unsubscribe_reason=None,
            confirmation_token_hash=None,
            confirmation_expires_at=None,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.SUBSCRIBE,
            entity=updated,
            description=f"Confirmed {updated.email} by hand",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def mark_unsubscribed(
        self,
        subscription_id: uuid.UUID,
        *,
        reason: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Subscription:
        """Take an address off the list on its owner's behalf.

        Someone who replies "take me off this" should not have to find the
        link themselves.
        """
        subscription = await self.repository.get_or_raise(subscription_id)
        if subscription.status == SubscriptionStatus.UNSUBSCRIBED:
            raise ConflictException(f"'{subscription.email}' is already unsubscribed.")

        previous_status = subscription.status
        updated = await self._leave(subscription, reason=reason)
        updated = await self.repository.update(updated, updated_by=actor_id)

        await self.activity.record(
            ActivityAction.UNSUBSCRIBE,
            entity=updated,
            description=f"Unsubscribed {updated.email} on request",
            old_values={"status": previous_status},
            new_values={"status": updated.status, "unsubscribe_reason": reason},
        )
        await self.session.commit()
        return updated

    async def mark_bounced(
        self, subscription_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Subscription:
        """Retire an address that mail keeps failing to reach.

        Kept out of every send, because continuing to mail a dead address is
        what costs the live ones their deliverability.
        """
        subscription = await self.repository.get_or_raise(subscription_id)
        if subscription.status == SubscriptionStatus.BOUNCED:
            raise ConflictException(
                f"'{subscription.email}' is already marked as bounced."
            )

        previous_status = subscription.status
        updated = await self.repository.update(
            subscription,
            status=SubscriptionStatus.BOUNCED.value,
            updated_by=actor_id,
        )

        await self.activity.record(
            ActivityAction.STATUS_CHANGE,
            entity=updated,
            description=f"Marked {updated.email} as bouncing",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def delete(self, subscription_id: uuid.UUID) -> None:
        """Soft delete, so the row survives for audit and restore.

        Worth being clear about what this is not: it is not how somebody
        leaves the list. Removing the row frees the address, and the next
        import would put it straight back. Use `mark_unsubscribed` for a
        person who asked to stop; use this for a row that should not have
        been created.
        """
        subscription = await self.repository.get_or_raise(subscription_id)
        before = snapshot(subscription)
        await self.repository.soft_delete(subscription)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=subscription,
            description=f"Deleted subscription {subscription.email!r}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, subscription_id: uuid.UUID) -> Subscription:
        subscription = await self.repository.get_or_raise(
            subscription_id, include_deleted=True
        )
        restored = await self.repository.restore(subscription)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored subscription {restored.email!r}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored
