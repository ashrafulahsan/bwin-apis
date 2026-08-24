"""Tests for the notification module.

The two things most worth pinning down here are audience resolution - who
actually ends up with a copy - and the counter arithmetic, because both fail
silently. A notification that reaches nobody still reports success, and a
read percentage above 100 looks like a rounding bug rather than a
double-counted read.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.activity_logs.models.activity_log import ActivityLog, ActivityModule
from app.modules.notifications.constants import (
    DeliveryType,
    NotificationPriority,
    NotificationType,
    SystemEvent,
)
from app.modules.notifications.models.notification import Notification
from app.modules.notifications.models.notification_recipient import (
    NotificationRecipient,
)
from app.modules.notifications.schemas.notification import (
    NotificationCreate,
    NotificationUpdate,
)
from app.modules.notifications.services.manager import NotificationManager
from app.modules.notifications.services.notification import NotificationService
from app.modules.notifications.services.user_notification import (
    UserNotificationService,
)
from app.modules.roles.models.role import Role
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_role import user_roles
from app.shared.utils.dates import utc_now


class Desk:
    """An admin, three learners in two roles, and a suspended account."""

    def __init__(
        self,
        service: NotificationService,
        *,
        admin: User,
        alice: User,
        bob: User,
        carol: User,
        suspended: User,
        student_role: Role,
        trainer_role: Role,
    ) -> None:
        self.service = service
        self.session = service.session
        self.admin = admin
        self.alice = alice
        self.bob = bob
        self.carol = carol
        self.suspended = suspended
        self.student_role = student_role
        self.trainer_role = trainer_role


async def _clear(session: AsyncSession) -> None:
    await session.execute(delete(NotificationRecipient))
    await session.execute(delete(Notification))
    await session.execute(delete(ActivityLog))
    await session.execute(delete(user_roles))
    await session.execute(delete(User))
    await session.execute(delete(Role).where(Role.is_system.is_(False)))
    await session.commit()


async def _user(
    session: AsyncSession,
    email: str,
    *,
    status: str = UserStatus.ACTIVE.value,
    role: Role | None = None,
) -> User:
    user = User(
        email=email,
        first_name=email.split("@")[0].title(),
        status=status,
        language="en",
    )
    session.add(user)
    await session.flush()

    if role is not None:
        await session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await session.flush()

    return user


@pytest.fixture
async def desk(session: AsyncSession) -> AsyncIterator[Desk]:
    await _clear(session)

    student_role = Role(
        name="Probe Student", slug="probe-student", level=10, is_system=False
    )
    trainer_role = Role(
        name="Probe Trainer", slug="probe-trainer", level=20, is_system=False
    )
    session.add_all([student_role, trainer_role])
    await session.flush()

    admin = await _user(session, "admin@probe.test")
    alice = await _user(session, "alice@probe.test", role=student_role)
    bob = await _user(session, "bob@probe.test", role=student_role)
    carol = await _user(session, "carol@probe.test", role=trainer_role)
    suspended = await _user(
        session,
        "suspended@probe.test",
        status=UserStatus.SUSPENDED.value,
        role=student_role,
    )
    await session.commit()

    yield Desk(
        NotificationService(session),
        admin=admin,
        alice=alice,
        bob=bob,
        carol=carol,
        suspended=suspended,
        student_role=student_role,
        trainer_role=trainer_role,
    )

    await _clear(session)


def payload(**overrides: object) -> NotificationCreate:
    values: dict[str, object] = {
        "title": "New PMP Batch",
        "short_message": "Registration is now open",
        "details_content": "<p>Details here...</p>",
        "delivery_type": DeliveryType.GLOBAL,
        "priority": NotificationPriority.HIGH,
    }
    values.update(overrides)
    return NotificationCreate(**values)  # type: ignore[arg-type]


# -- Request validation (no database) -------------------------------------


def test_a_targeted_delivery_needs_targets() -> None:
    """Reaching nobody while reporting success is the worst failure here."""
    for delivery in (DeliveryType.ROLE, DeliveryType.USER, DeliveryType.COURSE):
        with pytest.raises(ValidationError):
            payload(delivery_type=delivery, target_ids=[])


def test_a_global_delivery_refuses_targets() -> None:
    with pytest.raises(ValidationError):
        payload(delivery_type=DeliveryType.GLOBAL, target_ids=[uuid.uuid4()])


def test_expiry_must_follow_publication() -> None:
    moment = utc_now()
    with pytest.raises(ValidationError):
        payload(publish_at=moment, expires_at=moment - timedelta(hours=1))


# -- Audience resolution ---------------------------------------------------


async def test_a_global_notification_reaches_every_active_user(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)

    # Four active accounts; the suspended one is not one of them.
    assert notification.total_recipients == 4

    rows = (
        (
            await desk.session.execute(
                select(NotificationRecipient).where(
                    NotificationRecipient.notification_id == notification.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert desk.suspended.id not in {row.user_id for row in rows}


async def test_a_role_notification_reaches_only_that_role(desk: Desk) -> None:
    notification = await desk.service.create(
        payload(delivery_type=DeliveryType.ROLE, target_ids=[desk.student_role.id]),
        actor=desk.admin,
    )

    # Alice and Bob are students; the suspended student is still excluded.
    assert notification.total_recipients == 2

    rows = (
        (
            await desk.session.execute(
                select(NotificationRecipient.user_id).where(
                    NotificationRecipient.notification_id == notification.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(rows) == {desk.alice.id, desk.bob.id}


async def test_someone_in_two_targeted_roles_gets_one_copy(
    desk: Desk, session: AsyncSession
) -> None:
    """The unique pair is what makes overlapping audiences safe."""
    await session.execute(
        user_roles.insert().values(user_id=desk.alice.id, role_id=desk.trainer_role.id)
    )
    await session.commit()

    notification = await desk.service.create(
        payload(
            delivery_type=DeliveryType.ROLE,
            target_ids=[desk.student_role.id, desk.trainer_role.id],
        ),
        actor=desk.admin,
    )

    assert notification.total_recipients == 3


async def test_a_user_notification_reaches_only_those_users(desk: Desk) -> None:
    notification = await desk.service.create(
        payload(delivery_type=DeliveryType.USER, target_ids=[desk.carol.id]),
        actor=desk.admin,
    )

    assert notification.total_recipients == 1


async def test_an_unknown_target_is_refused_before_anything_is_written(
    desk: Desk,
) -> None:
    with pytest.raises(NotFoundException):
        await desk.service.create(
            payload(delivery_type=DeliveryType.USER, target_ids=[uuid.uuid4()]),
            actor=desk.admin,
        )

    _, total = await desk.service.list_notifications(
        PaginationParams(page=1, page_size=10)
    )
    assert total == 0


async def test_course_delivery_reports_the_missing_enrolment_table(
    desk: Desk,
) -> None:
    """It refuses loudly rather than sending to nobody.

    When enrolments exist this test changes to assert delivery; until then
    it pins the failure mode, because the alternative - a silent send to an
    empty audience - is the one outcome nobody would notice.
    """
    with pytest.raises(BadRequestException, match="enrolment"):
        await desk.service.create(
            payload(delivery_type=DeliveryType.COURSE, target_ids=[uuid.uuid4()]),
            actor=desk.admin,
        )


async def test_creation_is_logged(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)

    entry = (
        (
            await desk.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(notification.id))
            )
        )
        .scalars()
        .all()
    )[-1]

    assert entry.module == ActivityModule.NOTIFICATIONS
    assert entry.entity_type == "Notification"
    assert entry.new_values is not None
    assert entry.new_values["total_recipients"] == 4


# -- The recipient's view --------------------------------------------------


async def test_a_recipient_sees_their_own_copy(desk: Desk) -> None:
    await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    items, total = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert total == 1
    assert items[0].user_id == desk.alice.id


async def test_a_stranger_cannot_open_someone_elses_notification(
    desk: Desk,
) -> None:
    notification = await desk.service.create(
        payload(delivery_type=DeliveryType.USER, target_ids=[desk.alice.id]),
        actor=desk.admin,
    )
    service = UserNotificationService(desk.session)

    # 404 rather than 403: a 403 would confirm it exists and that somebody
    # else received it.
    with pytest.raises(NotFoundException):
        await service.open(notification.id, desk.bob)


async def test_an_unpublished_notification_is_not_shown(desk: Desk) -> None:
    await desk.service.create(
        payload(publish_at=utc_now() + timedelta(days=1)), actor=desk.admin
    )
    service = UserNotificationService(desk.session)

    _, total = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert total == 0
    assert await service.unread_count(desk.alice.id) == 0


async def test_a_withdrawn_notification_disappears_for_everyone(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    await desk.service.delete(notification.id, actor=desk.admin)

    _, total = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert total == 0


async def test_an_expired_notification_is_hidden_unless_asked_for(
    desk: Desk,
) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    await desk.service.repository.update(
        notification, expires_at=utc_now() - timedelta(hours=1)
    )
    await desk.session.commit()

    service = UserNotificationService(desk.session)

    _, hidden = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert hidden == 0

    _, shown = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10), include_expired=True
    )
    assert shown == 1

    # An expired notice must not keep the badge lit.
    assert await service.unread_count(desk.alice.id) == 0


# -- Read tracking ----------------------------------------------------------


async def test_the_first_read_stamps_and_counts_once(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    recipient = await service.open(notification.id, desk.alice)

    assert recipient.is_read is True
    assert recipient.read_at is not None
    assert recipient.read_count == 1

    await desk.session.refresh(notification)
    assert notification.total_reads == 1


async def test_re_reading_moves_read_count_but_not_total_reads(desk: Desk) -> None:
    """`total_reads` is the numerator of the read percentage."""
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    first = await service.open(notification.id, desk.alice)
    read_at = first.read_at

    again = await service.open(notification.id, desk.alice)

    assert again.read_count == 2
    assert again.read_at == read_at

    await desk.session.refresh(notification)
    assert notification.total_reads == 1
    # Two opens of the details page, by one person.
    assert notification.total_detail_views == 2


async def test_read_percentage_never_exceeds_one_hundred(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    for _ in range(3):
        await service.open(notification.id, desk.alice)

    stats = await desk.service.statistics(notification.id)
    assert stats.total_recipients == 4
    assert stats.total_reads == 1
    assert stats.read_percentage == 25.0


async def test_mark_read_does_not_count_a_details_view(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    recipient = await service.mark_read(notification.id, desk.alice)

    assert recipient.is_read is True
    assert recipient.details_viewed is False
    assert recipient.details_view_count == 0

    await desk.session.refresh(notification)
    assert notification.total_detail_views == 0


async def test_details_view_tracking(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    recipient = await service.open(notification.id, desk.alice, details_view=True)

    assert recipient.details_viewed is True
    assert recipient.details_view_count == 1
    assert recipient.details_viewed_at is not None
    assert recipient.last_viewed_at is not None


async def test_unread_count_tracks_reads(desk: Desk) -> None:
    await desk.service.create(payload(), actor=desk.admin)
    await desk.service.create(payload(title="Second"), actor=desk.admin)
    service = UserNotificationService(desk.session)

    assert await service.unread_count(desk.alice.id) == 2

    items, _ = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    await service.mark_read(items[0].notification_id, desk.alice)

    assert await service.unread_count(desk.alice.id) == 1


async def test_mark_all_read_counts_each_notification_once(desk: Desk) -> None:
    first = await desk.service.create(payload(), actor=desk.admin)
    second = await desk.service.create(payload(title="Second"), actor=desk.admin)
    service = UserNotificationService(desk.session)

    # Already read, so marking all read must not count it again.
    await service.mark_read(first.id, desk.alice)

    marked = await service.mark_all_read(desk.alice)
    assert marked == 1
    assert await service.unread_count(desk.alice.id) == 0

    await desk.session.refresh(first)
    await desk.session.refresh(second)
    assert first.total_reads == 1
    assert second.total_reads == 1


async def test_mark_all_read_on_an_empty_inbox_is_a_no_op(desk: Desk) -> None:
    service = UserNotificationService(desk.session)
    assert await service.mark_all_read(desk.alice) == 0


# -- Archiving ---------------------------------------------------------------


async def test_archiving_removes_it_from_the_default_list(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    await service.archive(notification.id, desk.alice)

    _, visible = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert visible == 0

    _, archived = await service.list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10), is_archived=True
    )
    assert archived == 1

    # Archiving is not deletion: the record that they were sent it remains.
    restored = await service.archive(notification.id, desk.alice, archived=False)
    assert restored.is_archived is False
    assert restored.archived_at is None


async def test_an_archived_notification_does_not_light_the_badge(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    await service.archive(notification.id, desk.alice)

    assert await service.unread_count(desk.alice.id) == 0


# -- Editing and withdrawal --------------------------------------------------


async def test_a_published_notification_cannot_be_rewritten(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)

    with pytest.raises(BadRequestException, match="already been published"):
        await desk.service.update(
            notification.id, NotificationUpdate(title="Rewritten"), actor=desk.admin
        )


async def test_a_published_notification_can_still_be_withdrawn(desk: Desk) -> None:
    """Deactivating withdraws it; it does not rewrite what people read."""
    notification = await desk.service.create(payload(), actor=desk.admin)

    updated = await desk.service.update(
        notification.id, NotificationUpdate(is_active=False), actor=desk.admin
    )
    assert updated.is_active is False

    _, total = await UserNotificationService(desk.session).list_for_user(
        desk.alice.id, PaginationParams(page=1, page_size=10)
    )
    assert total == 0


async def test_a_scheduled_notification_can_be_edited(desk: Desk) -> None:
    notification = await desk.service.create(
        payload(publish_at=utc_now() + timedelta(days=1)), actor=desk.admin
    )

    updated = await desk.service.update(
        notification.id,
        NotificationUpdate(title="Corrected before it went out"),
        actor=desk.admin,
    )
    assert updated.title == "Corrected before it went out"


async def test_rebuilding_an_audience_before_publication(desk: Desk) -> None:
    notification = await desk.service.create(
        payload(
            delivery_type=DeliveryType.USER,
            target_ids=[desk.alice.id],
            publish_at=utc_now() + timedelta(days=1),
        ),
        actor=desk.admin,
    )
    assert notification.total_recipients == 1

    updated = await desk.service.update(
        notification.id,
        NotificationUpdate(target_ids=[desk.bob.id, desk.carol.id]),
        actor=desk.admin,
    )

    assert updated.total_recipients == 2

    rows = (
        (
            await desk.session.execute(
                select(NotificationRecipient.user_id).where(
                    NotificationRecipient.notification_id == notification.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(rows) == {desk.bob.id, desk.carol.id}


async def test_a_published_audience_cannot_be_changed(desk: Desk) -> None:
    notification = await desk.service.create(
        payload(delivery_type=DeliveryType.USER, target_ids=[desk.alice.id]),
        actor=desk.admin,
    )

    with pytest.raises(BadRequestException, match="audience"):
        await desk.service.update(
            notification.id,
            NotificationUpdate(target_ids=[desk.bob.id]),
            actor=desk.admin,
        )


async def test_withdraw_and_restore(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)

    await desk.service.delete(notification.id, actor=desk.admin)
    with pytest.raises(NotFoundException):
        await desk.service.get(notification.id)

    restored = await desk.service.restore(notification.id, actor=desk.admin)
    assert restored.deleted_at is None


# -- Statistics ---------------------------------------------------------------


async def test_statistics_are_counted_from_the_recipient_rows(desk: Desk) -> None:
    notification = await desk.service.create(payload(), actor=desk.admin)
    service = UserNotificationService(desk.session)

    await service.open(notification.id, desk.alice)
    await service.open(notification.id, desk.bob)
    await service.mark_read(notification.id, desk.carol)
    await service.archive(notification.id, desk.alice)

    stats = await desk.service.statistics(notification.id)

    assert stats.total_recipients == 4
    assert stats.total_reads == 3
    assert stats.total_unread == 1
    # Carol only marked it read, so she is not a details viewer.
    assert stats.unique_detail_viewers == 2
    assert stats.total_archived == 1
    assert stats.read_percentage == 75.0
    assert stats.detail_view_percentage == 50.0


async def test_statistics_of_an_unsent_audience_do_not_divide_by_zero(
    desk: Desk, session: AsyncSession
) -> None:
    notification = Notification(
        title="Orphan",
        short_message="No audience",
        details_content="None",
        notification_type=NotificationType.SYSTEM.value,
        delivery_type=DeliveryType.USER.value,
    )
    session.add(notification)
    await session.commit()

    stats = await desk.service.statistics(notification.id)
    assert stats.total_recipients == 0
    assert stats.read_percentage == 0.0
    assert stats.detail_view_percentage == 0.0


# -- NotificationManager -------------------------------------------------------


async def test_the_manager_sends_to_named_users(desk: Desk) -> None:
    manager = NotificationManager(desk.session)

    notification = await manager.send(
        title="Course Completed",
        short_message="Congratulations",
        details_content="Your certificate is ready.",
        user_ids=[desk.alice.id, desk.bob.id],
    )
    await desk.session.commit()

    assert notification is not None
    assert notification.notification_type == NotificationType.SYSTEM
    assert notification.delivery_type == DeliveryType.USER
    assert notification.total_recipients == 2


async def test_the_manager_refuses_a_targeted_send_with_no_targets(
    desk: Desk,
) -> None:
    """Returning None beats writing a notification that reaches nobody."""
    manager = NotificationManager(desk.session)

    result = await manager.send(
        title="Nobody",
        short_message="Nobody",
        details_content="Nobody",
        delivery_type=DeliveryType.USER,
        user_ids=[],
    )

    assert result is None


async def test_the_manager_infers_a_global_send(desk: Desk) -> None:
    manager = NotificationManager(desk.session)

    notification = await manager.send(
        title="Maintenance tonight",
        short_message="Back by 2am",
        details_content="Scheduled maintenance.",
    )
    await desk.session.commit()

    assert notification is not None
    assert notification.delivery_type == DeliveryType.GLOBAL
    assert notification.total_recipients == 4


async def test_an_event_supplies_its_own_wording(desk: Desk) -> None:
    manager = NotificationManager(desk.session)

    notification = await manager.send_event(
        SystemEvent.CERTIFICATE_GENERATED, user_ids=[desk.alice.id]
    )
    await desk.session.commit()

    assert notification is not None
    assert notification.title == "Your certificate is ready"
    assert notification.priority == NotificationPriority.NORMAL


async def test_an_event_can_be_overridden_at_the_call_site(desk: Desk) -> None:
    manager = NotificationManager(desk.session)

    notification = await manager.send_event(
        SystemEvent.LIVE_CLASS_REMINDER,
        user_ids=[desk.alice.id],
        details_content="Your PMP session starts at 7pm.",
    )
    await desk.session.commit()

    assert notification is not None
    assert notification.details_content == "Your PMP session starts at 7pm."
    # The template's priority still applies where nothing overrode it.
    assert notification.priority == NotificationPriority.HIGH


async def test_the_manager_leaves_committing_to_its_caller(desk: Desk) -> None:
    """A notice about something that was rolled back must roll back with it."""
    manager = NotificationManager(desk.session)

    await manager.send(
        title="Rolled back",
        short_message="Should not survive",
        details_content="Should not survive",
        user_ids=[desk.alice.id],
    )
    await desk.session.rollback()

    _, total = await desk.service.list_notifications(
        PaginationParams(page=1, page_size=10)
    )
    assert total == 0
