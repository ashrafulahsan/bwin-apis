"""Tests for the contact inquiry module.

The public submission path gets the most attention here, because it is the
one endpoint in the platform that anyone on the internet can reach: its
validation, its throttle and its silence about what it already knows are all
load-bearing.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import NotFoundException, TooManyRequestsException
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityLog,
    ActivityModule,
)
from app.modules.inquiries.constants import (
    DEFAULT_RATE_LIMIT_MAX,
    DEFAULT_RATE_LIMIT_WINDOW_MINUTES,
    InquirySettingKey,
    InquiryStatus,
    InterestedIn,
)
from app.modules.inquiries.models.contact_inquiry import ContactInquiry
from app.modules.inquiries.schemas.contact_inquiry import (
    InquiryCreate,
    InquiryStatusUpdate,
    InquiryUpdate,
)
from app.modules.inquiries.services.contact_inquiry import ContactInquiryService
from app.modules.users.models.user import User
from app.modules.users.models.user_role import user_roles


class Desk:
    """The service under test plus the member of staff acting on it."""

    def __init__(self, service: ContactInquiryService, staff: User) -> None:
        self.service = service
        self.session = service.session
        self.staff = staff


async def _clear(session: AsyncSession) -> None:
    await session.execute(delete(ContactInquiry))
    await session.execute(delete(ActivityLog))
    await session.execute(delete(user_roles))
    await session.execute(delete(User))
    await session.commit()


async def _set_rate_limit(session: AsyncSession, maximum: str, window: str) -> None:
    """Write the throttle settings, creating the rows if they are absent.

    `test_settings` truncates `settings`, so the rows this module's migration
    seeds are not guaranteed to be there under the full suite.
    """
    for key, value, value_type in (
        (InquirySettingKey.RATE_LIMIT_MAX.value, maximum, "integer"),
        (
            InquirySettingKey.RATE_LIMIT_WINDOW_MINUTES.value,
            window,
            "integer",
        ),
    ):
        await session.execute(
            text(
                'INSERT INTO settings (key, value, value_type, "group", label, '
                "description, is_secret, is_system) "
                "VALUES (:key, :value, :value_type, 'general', :key, "
                "'Set by the test suite.', false, true) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"key": key, "value": value, "value_type": value_type},
        )
    await session.commit()


@pytest.fixture
async def desk(session: AsyncSession) -> AsyncIterator[Desk]:
    await _clear(session)
    await _set_rate_limit(
        session, str(DEFAULT_RATE_LIMIT_MAX), str(DEFAULT_RATE_LIMIT_WINDOW_MINUTES)
    )

    staff = User(
        email="desk@probe.test", first_name="Desk", status="active", language="en"
    )
    session.add(staff)
    await session.commit()

    yield Desk(ContactInquiryService(session), staff)

    await _clear(session)


def payload(**overrides: object) -> InquiryCreate:
    values: dict[str, object] = {
        "full_name": "John Doe",
        "email": "john@example.com",
        "phone": "+8801712345678",
        "interested_in": InterestedIn.CONSULTANCY,
        "message": "Need consultancy support.",
    }
    values.update(overrides)
    return InquiryCreate(**values)  # type: ignore[arg-type]


# -- Validation (no database) --------------------------------------------


def test_a_whitespace_only_name_is_rejected() -> None:
    """`min_length` runs before stripping, so this needs its own guard."""
    with pytest.raises(ValidationError):
        payload(full_name="   ")


def test_a_malformed_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        payload(email="not-an-email")


def test_an_unknown_interest_is_rejected() -> None:
    with pytest.raises(ValidationError):
        payload(interested_in="crypto_mining")


def test_every_form_option_is_accepted() -> None:
    for option in InterestedIn:
        assert payload(interested_in=option).interested_in is option


def test_text_is_trimmed() -> None:
    parsed = payload(full_name="  John Doe  ", message="  Hello  ")
    assert parsed.full_name == "John Doe"
    assert parsed.message == "Hello"


def test_a_blank_message_becomes_null() -> None:
    """An empty box means "they wrote nothing", not "they wrote ''"."""
    assert payload(message="   ").message is None
    assert payload(message="").message is None
    assert payload(message=None).message is None


def test_the_email_is_lowercased() -> None:
    assert payload(email="John@Example.COM").email == "john@example.com"


def test_a_local_phone_number_is_normalized() -> None:
    assert payload(phone="01712-345678").phone == "+8801712345678"


def test_an_unusable_phone_number_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        payload(phone="abc")

    # The failure names the field, so a form can render it in place.
    assert any(error["loc"] == ("phone",) for error in caught.value.errors())


def test_a_missing_phone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InquiryCreate(
            full_name="John Doe",
            email="john@example.com",
            interested_in=InterestedIn.CONSULTANCY,  # type: ignore[call-arg]
        )


# -- Submission -----------------------------------------------------------


async def test_a_submission_is_stored_as_new_and_unread(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    assert inquiry.status == InquiryStatus.NEW
    assert inquiry.is_read is False
    assert inquiry.read_at is None
    assert inquiry.email == "john@example.com"
    assert inquiry.interested_in == InterestedIn.CONSULTANCY


async def test_provenance_is_recorded(desk: Desk) -> None:
    inquiry = await desk.service.submit(
        payload(), ip_address="203.0.113.10", user_agent="Mozilla/5.0 probe"
    )

    assert inquiry.ip_address == "203.0.113.10"
    assert inquiry.user_agent == "Mozilla/5.0 probe"


async def test_an_overlong_user_agent_is_truncated(desk: Desk) -> None:
    inquiry = await desk.service.submit(
        payload(), ip_address="203.0.113.10", user_agent="x" * 5000
    )

    assert inquiry.user_agent is not None
    assert len(inquiry.user_agent) == 512


async def test_submission_is_logged_without_copying_the_message(desk: Desk) -> None:
    """The audit entry records that it happened, not the body of it again."""
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    entry = (
        (
            await desk.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(inquiry.id))
            )
        )
        .scalars()
        .all()
    )[-1]

    assert entry.module == ActivityModule.INQUIRIES
    assert entry.action == ActivityAction.CREATE
    assert entry.entity_type == "ContactInquiry"
    assert entry.new_values is not None
    assert "message" not in entry.new_values


async def test_a_repeat_of_the_same_form_does_not_create_a_second_row(
    desk: Desk,
) -> None:
    """A double-clicked button is one inquiry, not two for somebody to chase."""
    first = await desk.service.submit(payload(), ip_address="203.0.113.10")
    second = await desk.service.submit(payload(), ip_address="203.0.113.10")

    assert first.id == second.id

    _, total = await desk.service.list_inquiries(PaginationParams(page=1, page_size=10))
    assert total == 1


async def test_a_different_message_from_the_same_address_is_a_new_inquiry(
    desk: Desk,
) -> None:
    await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.submit(
        payload(message="Actually, about automation."), ip_address="203.0.113.10"
    )

    _, total = await desk.service.list_inquiries(PaginationParams(page=1, page_size=10))
    assert total == 2


# -- Rate limiting --------------------------------------------------------


async def test_the_rate_limit_stops_a_flood_from_one_address(
    desk: Desk, session: AsyncSession
) -> None:
    await _set_rate_limit(session, "3", "15")
    service = ContactInquiryService(session)

    for index in range(3):
        await service.submit(
            payload(email=f"visitor{index}@example.com"), ip_address="198.51.100.7"
        )

    with pytest.raises(TooManyRequestsException):
        await service.submit(
            payload(email="visitor-blocked@example.com"), ip_address="198.51.100.7"
        )


async def test_the_rate_limit_is_per_address(desk: Desk, session: AsyncSession) -> None:
    await _set_rate_limit(session, "1", "15")
    service = ContactInquiryService(session)

    await service.submit(payload(email="a@example.com"), ip_address="198.51.100.7")

    # A different visitor is unaffected by the first one's burst.
    other = await service.submit(
        payload(email="b@example.com"), ip_address="198.51.100.8"
    )
    assert other.id is not None


async def test_a_zero_maximum_disables_the_rate_limit(
    desk: Desk, session: AsyncSession
) -> None:
    await _set_rate_limit(session, "0", "15")
    service = ContactInquiryService(session)

    for index in range(6):
        await service.submit(
            payload(email=f"burst{index}@example.com"), ip_address="198.51.100.9"
        )

    _, total = await service.list_inquiries(PaginationParams(page=1, page_size=20))
    assert total == 6


async def test_a_request_with_no_address_is_not_refused(
    desk: Desk, session: AsyncSession
) -> None:
    """Refusing everyone we cannot identify would break the form behind a proxy."""
    await _set_rate_limit(session, "1", "15")
    service = ContactInquiryService(session)

    for index in range(3):
        await service.submit(payload(email=f"anon{index}@example.com"), ip_address=None)

    _, total = await service.list_inquiries(PaginationParams(page=1, page_size=20))
    assert total == 3


# -- Reading --------------------------------------------------------------


async def test_opening_an_inquiry_marks_it_read(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    opened = await desk.service.get_and_mark_read(inquiry.id, actor=desk.staff)

    assert opened.is_read is True
    assert opened.read_at is not None
    assert opened.read_by == desk.staff.id


async def test_a_later_view_does_not_move_the_first_read_timestamp(
    desk: Desk,
) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    first = await desk.service.get_and_mark_read(inquiry.id, actor=desk.staff)
    first_read_at = first.read_at

    second = await desk.service.get_and_mark_read(inquiry.id, actor=desk.staff)

    assert second.read_at == first_read_at


async def test_every_view_is_logged(desk: Desk) -> None:
    """Who looked at a member of the public's details is worth answering."""
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    await desk.service.get_and_mark_read(inquiry.id, actor=desk.staff)
    await desk.service.get_and_mark_read(inquiry.id, actor=desk.staff)

    views = (
        (
            await desk.session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == str(inquiry.id),
                    ActivityLog.action == ActivityAction.VIEW.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(views) == 2


async def test_an_unknown_inquiry_is_a_not_found(desk: Desk) -> None:
    with pytest.raises(NotFoundException):
        await desk.service.get(uuid.uuid4())


# -- Listing, search and filters -----------------------------------------


async def test_search_matches_name_email_and_phone(desk: Desk) -> None:
    await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.submit(
        payload(
            full_name="Ayesha Rahman",
            email="ayesha@example.com",
            phone="+8801912345678",
            interested_in=InterestedIn.SKILL_DEVELOPMENT,
        ),
        ip_address="203.0.113.11",
    )

    for term, expected in (
        ("Ayesha", "ayesha@example.com"),
        ("ayesha@example.com", "ayesha@example.com"),
        ("+8801912345678", "ayesha@example.com"),
    ):
        items, total = await desk.service.list_inquiries(
            PaginationParams(page=1, page_size=10), search=term
        )
        assert total == 1, term
        assert items[0].email == expected


async def test_filters_narrow_the_listing(desk: Desk) -> None:
    first = await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.submit(
        payload(
            email="ayesha@example.com",
            interested_in=InterestedIn.SKILL_DEVELOPMENT,
        ),
        ip_address="203.0.113.11",
    )
    await desk.service.change_status(
        first.id, InquiryStatusUpdate(status=InquiryStatus.CONTACTED), actor=desk.staff
    )

    _, contacted = await desk.service.list_inquiries(
        PaginationParams(page=1, page_size=10), status=InquiryStatus.CONTACTED
    )
    assert contacted == 1

    _, skills = await desk.service.list_inquiries(
        PaginationParams(page=1, page_size=10),
        interested_in=InterestedIn.SKILL_DEVELOPMENT,
    )
    assert skills == 1

    _, unread = await desk.service.list_inquiries(
        PaginationParams(page=1, page_size=10), is_read=False
    )
    assert unread == 2


async def test_the_listing_is_newest_first(desk: Desk) -> None:
    await desk.service.submit(
        payload(email="first@example.com"), ip_address="203.0.113.10"
    )
    await desk.service.submit(
        payload(email="second@example.com"), ip_address="203.0.113.11"
    )

    items, _ = await desk.service.list_inquiries(PaginationParams(page=1, page_size=10))
    assert items[0].email == "second@example.com"


# -- Status and notes -----------------------------------------------------


async def test_status_change_records_the_previous_value(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    updated = await desk.service.change_status(
        inquiry.id,
        InquiryStatusUpdate(
            status=InquiryStatus.CONTACTED, notes="Client contacted via phone."
        ),
        actor=desk.staff,
    )

    assert updated.status == InquiryStatus.CONTACTED
    assert updated.notes == "Client contacted via phone."
    assert updated.updated_by == desk.staff.id

    entry = (
        (
            await desk.session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == str(inquiry.id),
                    ActivityLog.action == ActivityAction.STATUS_CHANGE.value,
                )
            )
        )
        .scalars()
        .all()
    )[-1]

    # `updated_by` moves too - the diff records every field that changed,
    # not only the one the caller was thinking about.
    assert entry.old_values == {
        "status": "new",
        "notes": None,
        "updated_by": None,
    }
    assert entry.new_values is not None
    assert entry.new_values["status"] == "contacted"


async def test_omitting_notes_leaves_the_existing_note_alone(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.change_status(
        inquiry.id,
        InquiryStatusUpdate(status=InquiryStatus.CONTACTED, notes="Called them."),
        actor=desk.staff,
    )

    updated = await desk.service.change_status(
        inquiry.id,
        InquiryStatusUpdate(status=InquiryStatus.IN_PROGRESS),
        actor=desk.staff,
    )

    assert updated.notes == "Called them."


async def test_sending_notes_as_null_clears_the_note(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.change_status(
        inquiry.id,
        InquiryStatusUpdate(status=InquiryStatus.CONTACTED, notes="Called them."),
        actor=desk.staff,
    )

    updated = await desk.service.change_status(
        inquiry.id,
        InquiryStatusUpdate(status=InquiryStatus.IN_PROGRESS, notes=None),
        actor=desk.staff,
    )

    assert updated.notes is None


async def test_every_status_value_is_accepted(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    for status in InquiryStatus:
        updated = await desk.service.change_status(
            inquiry.id, InquiryStatusUpdate(status=status), actor=desk.staff
        )
        assert updated.status == status


# -- Correction, deletion and statistics ---------------------------------


async def test_a_correction_normalizes_the_phone_number(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    updated = await desk.service.update(
        inquiry.id, InquiryUpdate(phone="01911-111111"), actor=desk.staff
    )

    assert updated.phone == "+8801911111111"


async def test_delete_is_a_soft_delete_and_is_logged(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")

    await desk.service.delete(inquiry.id, actor=desk.staff)

    with pytest.raises(NotFoundException):
        await desk.service.get(inquiry.id)

    # The row is still there, which is what makes the deletion auditable.
    still_there = await desk.session.get(ContactInquiry, inquiry.id)
    assert still_there is not None
    assert still_there.deleted_at is not None

    entry = (
        (
            await desk.session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == str(inquiry.id),
                    ActivityLog.action == ActivityAction.DELETE.value,
                )
            )
        )
        .scalars()
        .all()
    )[-1]
    assert entry.module == ActivityModule.INQUIRIES


async def test_a_deleted_inquiry_can_be_restored(desk: Desk) -> None:
    inquiry = await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.delete(inquiry.id, actor=desk.staff)

    restored = await desk.service.restore(inquiry.id, actor=desk.staff)
    assert restored.deleted_at is None


async def test_statistics_count_the_inbox(desk: Desk) -> None:
    first = await desk.service.submit(payload(), ip_address="203.0.113.10")
    await desk.service.submit(
        payload(
            email="ayesha@example.com",
            interested_in=InterestedIn.SKILL_DEVELOPMENT,
        ),
        ip_address="203.0.113.11",
    )
    await desk.service.change_status(
        first.id, InquiryStatusUpdate(status=InquiryStatus.CONVERTED), actor=desk.staff
    )
    await desk.service.get_and_mark_read(first.id, actor=desk.staff)

    stats = await desk.service.statistics()

    assert stats.total == 2
    assert stats.unread == 1
    # `converted` is finished work, so it is not open.
    assert stats.open == 1
    assert stats.by_status["converted"] == 1
    assert stats.by_interest[InterestedIn.SKILL_DEVELOPMENT.value] == 1
