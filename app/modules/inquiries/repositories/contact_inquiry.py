"""Data access for contact inquiries."""

from datetime import datetime

from sqlalchemy import func, select

from app.modules.inquiries.constants import CLOSED_STATUSES, InquiryStatus
from app.modules.inquiries.models.contact_inquiry import ContactInquiry
from app.shared.repositories.base import BaseRepository


class ContactInquiryRepository(BaseRepository[ContactInquiry]):
    model = ContactInquiry
    #: Newest first is what an inbox means.
    default_sort_by = "created_at"

    async def count_from_address_since(self, ip_address: str, since: datetime) -> int:
        """Submissions from one address inside the rate limit window.

        Soft deleted rows are counted deliberately: deleting a flood is how
        an operator cleans up after it, and if that reset the limit the
        cleanup would reopen the door.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(ContactInquiry)
            .where(
                ContactInquiry.ip_address == ip_address,
                ContactInquiry.created_at >= since,
            )
        )
        return int(result.scalar_one())

    async def recent_duplicate(
        self, email: str, since: datetime
    ) -> ContactInquiry | None:
        """The same address asking again within the window, if it did.

        Used to answer a repeat submission with the same success message
        without writing a second row - a visitor double-clicking the button
        should not produce two inquiries for somebody to chase twice.
        """
        result = await self.session.execute(
            select(ContactInquiry)
            .where(
                ContactInquiry.email == email,
                ContactInquiry.created_at >= since,
                ContactInquiry.deleted_at.is_(None),
            )
            .order_by(ContactInquiry.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # -- Dashboard --------------------------------------------------------

    async def count_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(ContactInquiry.status, func.count())
            .where(ContactInquiry.deleted_at.is_(None))
            .group_by(ContactInquiry.status)
        )
        counts = {status.value: 0 for status in InquiryStatus}
        counts.update({row[0]: int(row[1]) for row in result.all()})
        return counts

    async def count_by_interest(self) -> dict[str, int]:
        result = await self.session.execute(
            select(ContactInquiry.interested_in, func.count())
            .where(ContactInquiry.deleted_at.is_(None))
            .group_by(ContactInquiry.interested_in)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def count_unread(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ContactInquiry)
            .where(
                ContactInquiry.deleted_at.is_(None),
                ContactInquiry.is_read.is_(False),
            )
        )
        return int(result.scalar_one())

    async def count_open(self) -> int:
        """Inquiries somebody still has to do something about."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ContactInquiry)
            .where(
                ContactInquiry.deleted_at.is_(None),
                ContactInquiry.status.notin_(
                    [status.value for status in CLOSED_STATUSES]
                ),
            )
        )
        return int(result.scalar_one())
