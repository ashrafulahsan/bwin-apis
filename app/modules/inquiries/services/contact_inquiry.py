"""Business logic for contact inquiries.

Two audiences, and the split runs through the whole file. `submit` is reached
by anyone on the internet, so it says as little as possible, writes as little
as possible, and is rate limited. Everything below it is reached by staff who
have already been authenticated and authorized at the route, so it is free to
be explicit about what went wrong.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import TooManyRequestsException
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.inquiries.constants import (
    CLOSED_STATUSES,
    DEFAULT_RATE_LIMIT_MAX,
    DEFAULT_RATE_LIMIT_WINDOW_MINUTES,
    INQUIRY_RATE_LIMITED_MESSAGE,
    INQUIRY_SEARCH_FIELDS,
    INQUIRY_USER_AGENT_MAX_LENGTH,
    InquirySettingKey,
    InquiryStatus,
    InterestedIn,
)
from app.modules.inquiries.models.contact_inquiry import ContactInquiry
from app.modules.inquiries.repositories.contact_inquiry import ContactInquiryRepository
from app.modules.inquiries.schemas.contact_inquiry import (
    InquiryCreate,
    InquiryStatistics,
    InquiryStatusUpdate,
    InquiryUpdate,
)
from app.modules.settings.services.setting import SettingService
from app.modules.users.models.user import User
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)

#: How long after an identical submission a repeat is treated as the same
#: inquiry rather than a new one. Short: it exists to absorb a double-clicked
#: button, not to stop somebody genuinely writing in twice in an afternoon.
DUPLICATE_WINDOW = timedelta(minutes=5)


class ContactInquiryService:
    """Accepts inquiries from the public, and manages them for staff."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ContactInquiryRepository(session)
        self.settings = SettingService(session)
        self.activity = ActivityLogService(session, ActivityModule.INQUIRIES)

    # -- Public ------------------------------------------------------------

    async def submit(
        self,
        payload: InquiryCreate,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ContactInquiry:
        """Record a submission from the public form.

        Returns the inquiry so the router can hand it to a background task,
        but the router replies with one fixed sentence either way - see
        `INQUIRY_SUBMITTED_MESSAGE`. A repeat within the duplicate window
        returns the original rather than writing a second row.
        """
        await self._enforce_rate_limit(ip_address)

        existing = await self.repository.recent_duplicate(
            payload.email, utc_now() - DUPLICATE_WINDOW
        )
        if existing is not None and self._is_same_submission(existing, payload):
            logger.info("Ignoring a repeat contact inquiry within its window")
            return existing

        inquiry = await self.repository.create(
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            interested_in=payload.interested_in.value,
            message=payload.message,
            status=InquiryStatus.NEW.value,
            ip_address=ip_address,
            user_agent=(
                user_agent[:INQUIRY_USER_AGENT_MAX_LENGTH] if user_agent else None
            ),
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=inquiry,
            description=f"Contact inquiry submitted by {inquiry.email}",
            # `snapshot` is not used here: it would copy the message body and
            # the user agent into the audit log, duplicating personal data
            # into a second table for no benefit an auditor would notice.
            new_values={
                "email": inquiry.email,
                "interested_in": inquiry.interested_in,
                "status": inquiry.status,
            },
        )

        await self.session.commit()
        return inquiry

    @staticmethod
    def _is_same_submission(existing: ContactInquiry, payload: InquiryCreate) -> bool:
        """Whether a repeat is the same form, not a second genuine inquiry."""
        return (
            existing.full_name == payload.full_name
            and existing.phone == payload.phone
            and existing.interested_in == payload.interested_in.value
            and existing.message == payload.message
        )

    async def _enforce_rate_limit(self, ip_address: str | None) -> None:
        """Refuse a caller who is submitting faster than a person could.

        Counted in the database rather than in process memory. An in-memory
        counter is per worker and empties on restart, so under more than one
        worker it lets through a multiple of the limit and a redeploy clears
        it entirely. The table is the only thing every worker agrees on.

        A request with no resolvable address is let through: an address is
        also what identifies the caller, and refusing everyone we cannot
        identify would break the form behind any proxy that strips it.
        """
        if not ip_address:
            return

        maximum = await self.settings.number(
            InquirySettingKey.RATE_LIMIT_MAX, DEFAULT_RATE_LIMIT_MAX
        )
        if maximum <= 0:
            return

        window_minutes = await self.settings.number(
            InquirySettingKey.RATE_LIMIT_WINDOW_MINUTES,
            DEFAULT_RATE_LIMIT_WINDOW_MINUTES,
        )
        since = utc_now() - timedelta(minutes=max(window_minutes, 1))

        recent = await self.repository.count_from_address_since(ip_address, since)
        if recent >= maximum:
            logger.warning(
                "Contact inquiry rate limit reached: %s submissions in %s minutes",
                recent,
                window_minutes,
            )
            raise TooManyRequestsException(INQUIRY_RATE_LIMITED_MESSAGE)

    async def notification_settings(self) -> tuple[str | None, bool]:
        """Where the desk notification goes, and whether to acknowledge."""
        recipient = await self.settings.value(InquirySettingKey.NOTIFY_EMAIL)
        acknowledge = await self.settings.flag(
            InquirySettingKey.ACKNOWLEDGE_SUBMITTER, default=True
        )
        return recipient, acknowledge

    # -- Administrative reads ----------------------------------------------

    async def get(self, inquiry_id: uuid.UUID) -> ContactInquiry:
        return await self.repository.get_or_raise(inquiry_id)

    async def list_inquiries(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: InquiryStatus | None = None,
        interested_in: InterestedIn | None = None,
        is_read: bool | None = None,
        open_only: bool = False,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[ContactInquiry], int]:
        """The admin inbox: newest first unless the caller says otherwise."""
        filters: list[Filter] = []

        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if interested_in is not None:
            filters.append(Filter.eq("interested_in", interested_in.value))
        if is_read is not None:
            filters.append(Filter.eq("is_read", is_read))
        if open_only:
            filters.append(
                Filter.not_in("status", [item.value for item in CLOSED_STATUSES])
            )
        if date_from is not None:
            filters.append(Filter.gte("created_at", date_from))
        if date_to is not None:
            filters.append(Filter.lte("created_at", date_to))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(INQUIRY_SEARCH_FIELDS),
            sort_by=sort_by or "created_at",
            sort_order=sort_order,
        )

    async def get_and_mark_read(
        self, inquiry_id: uuid.UUID, *, actor: User
    ) -> ContactInquiry:
        """Open an inquiry, marking it read the first time anyone does.

        `read_at` and `read_by` record the first view only - "when did we
        first see this" is the service-level question worth answering, and
        overwriting them on every open would destroy it. Every view,
        including the later ones, is written to the activity log: these rows
        hold a member of the public's name, phone number and email, and who
        looked at them is worth being able to answer.
        """
        inquiry = await self.repository.get_or_raise(inquiry_id)

        first_view = not inquiry.is_read
        if first_view:
            await self.repository.update(
                inquiry, is_read=True, read_at=utc_now(), read_by=actor.id
            )

        await self.activity.record(
            ActivityAction.VIEW,
            entity=inquiry,
            description=f"Viewed contact inquiry from {inquiry.email}",
            new_values={"first_view": first_view},
        )
        await self.session.commit()
        return inquiry

    async def statistics(self) -> InquiryStatistics:
        by_status = await self.repository.count_by_status()

        return InquiryStatistics(
            total=sum(by_status.values()),
            unread=await self.repository.count_unread(),
            open=await self.repository.count_open(),
            by_status=by_status,
            by_interest=await self.repository.count_by_interest(),
        )

    # -- Administrative writes ---------------------------------------------

    async def change_status(
        self, inquiry_id: uuid.UUID, payload: InquiryStatusUpdate, *, actor: User
    ) -> ContactInquiry:
        """Move an inquiry along, recording what it moved from.

        `notes` is only touched when the field is present in the request:
        omitting it leaves the existing note alone, while sending `null`
        clears it. Without that distinction a status change would silently
        wipe whatever the last person wrote.
        """
        inquiry = await self.repository.get_or_raise(inquiry_id)

        changes: dict[str, Any] = {
            "status": payload.status.value,
            "updated_by": actor.id,
        }
        if "notes" in payload.model_fields_set:
            changes["notes"] = payload.notes

        before = snapshot(inquiry, fields=changes.keys())
        updated = await self.repository.update(inquiry, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.STATUS_CHANGE,
                entity=updated,
                description=(
                    f"Contact inquiry from {updated.email} moved to "
                    f"{payload.status.value}"
                ),
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def update(
        self, inquiry_id: uuid.UUID, payload: InquiryUpdate, *, actor: User
    ) -> ContactInquiry:
        """Correct an inquiry's details, e.g. a mistyped number."""
        inquiry = await self.repository.get_or_raise(inquiry_id)

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return inquiry

        if "interested_in" in changes and changes["interested_in"] is not None:
            changes["interested_in"] = changes["interested_in"].value
        changes["updated_by"] = actor.id

        before = snapshot(inquiry, fields=changes.keys())
        updated = await self.repository.update(inquiry, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated contact inquiry from {updated.email}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def mark_unread(
        self, inquiry_id: uuid.UUID, *, actor: User
    ) -> ContactInquiry:
        """Put an inquiry back in the unread pile, to come back to it."""
        inquiry = await self.repository.get_or_raise(inquiry_id)
        updated = await self.repository.update(
            inquiry, is_read=False, updated_by=actor.id
        )

        await self.activity.record(
            ActivityAction.UPDATE,
            entity=updated,
            description=f"Marked contact inquiry from {updated.email} unread",
            old_values={"is_read": True},
            new_values={"is_read": False},
        )
        await self.session.commit()
        return updated

    async def delete(self, inquiry_id: uuid.UUID, *, actor: User) -> None:
        """Soft delete. The row stays, so the deletion itself is auditable."""
        inquiry = await self.repository.get_or_raise(inquiry_id)
        before = snapshot(inquiry, exclude={"user_agent", "message"})

        await self.repository.soft_delete(inquiry)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=inquiry,
            description=f"Deleted contact inquiry from {inquiry.email}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, inquiry_id: uuid.UUID, *, actor: User) -> ContactInquiry:
        inquiry = await self.repository.get_or_raise(inquiry_id, include_deleted=True)
        restored = await self.repository.restore(inquiry)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored contact inquiry from {restored.email}",
            new_values={"status": restored.status},
        )
        await self.session.commit()
        return restored
