"""Tests for the support ticket module.

The fixtures build four real users holding the real permission sets, because
almost everything worth testing here is an authorization rule and a fake
permission set would test nothing.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.modules.activity_logs.models.activity_log import ActivityLog, ActivityModule
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.roles.models.role import Role
from app.modules.settings.models.setting import Setting
from app.modules.support import policy
from app.modules.support.constants import (
    SUPPORT_TICKET_CATEGORY_TYPE_SLUG,
    SupportSettingKey,
    TicketPriority,
    TicketStatus,
    can_transition,
)
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.models.support_ticket_activity import SupportTicketActivity
from app.modules.support.models.support_ticket_assignment import (
    SupportTicketAssignment,
)
from app.modules.support.models.support_ticket_attachment import (
    SupportTicketAttachment,
)
from app.modules.support.models.support_ticket_feedback import SupportTicketFeedback
from app.modules.support.models.support_ticket_message import SupportTicketMessage
from app.modules.support.models.support_ticket_status_history import (
    SupportTicketStatusHistory,
)
from app.modules.support.policy import TicketScope
from app.modules.support.schemas.ticket import (
    ActivityRead,
    AdminTicketCreate,
    FeedbackCreate,
    TicketAssign,
    TicketCreate,
    TicketEscalate,
    TicketMerge,
    TicketPriorityChange,
    TicketStatusChange,
    TicketUpdate,
)
from app.modules.support.services.export import SupportExportService
from app.modules.support.services.stats import SupportStatsService
from app.modules.support.services.ticket import SupportTicketService
from app.modules.users.models.user import User
from app.modules.users.models.user_role import user_roles
from app.modules.users.repositories.user import UserRepository


class Desk:
    """The people and fixtures one test needs, assembled once."""

    def __init__(
        self,
        service: SupportTicketService,
        *,
        student: User,
        other_student: User,
        trainer: User,
        admin: User,
        category: Category,
    ) -> None:
        self.service = service
        self.session = service.session
        self.student = student
        self.other_student = other_student
        self.trainer = trainer
        self.admin = admin
        self.category = category


async def _role_with(session: AsyncSession, slug: str, codes: list[str]) -> Role:
    """A role holding exactly `codes`, reusing the seeded permission rows."""
    role = Role(name=f"Probe {slug}", slug=slug, level=10, is_system=False)
    session.add(role)
    await session.flush()

    if codes:
        permissions = (
            (
                await session.execute(
                    select(Permission).where(Permission.code.in_(codes))
                )
            )
            .scalars()
            .all()
        )
        assert len(permissions) == len(codes), (
            f"missing seeded permissions for {slug}: "
            f"{set(codes) - {p.code for p in permissions}}"
        )
        for permission in permissions:
            await session.execute(
                role_permissions.insert().values(
                    role_id=role.id, permission_id=permission.id
                )
            )

    return role


async def _user_with_role(session: AsyncSession, email: str, role: Role) -> User:
    user = User(
        email=email,
        first_name=email.split("@")[0].title(),
        status="active",
        language="en",
    )
    session.add(user)
    await session.flush()
    await session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    await session.flush()
    return user


async def _clear(session: AsyncSession) -> None:
    """Remove everything the suite creates, children before parents."""
    for model in (
        SupportTicketActivity,
        SupportTicketStatusHistory,
        SupportTicketAssignment,
        SupportTicketFeedback,
        SupportTicketAttachment,
        SupportTicketMessage,
    ):
        await session.execute(delete(model))

    # `merged_into_id` is a self reference, so it has to be cleared before
    # the rows it points at can go.
    await session.execute(SupportTicket.__table__.update().values(merged_into_id=None))
    await session.execute(delete(SupportTicket))
    await session.execute(delete(ActivityLog))
    await session.execute(delete(user_roles))
    await session.execute(delete(User))
    await session.execute(
        delete(role_permissions).where(
            role_permissions.c.role_id.in_(
                select(Role.id).where(Role.is_system.is_(False))
            )
        )
    )
    await session.execute(delete(Role).where(Role.is_system.is_(False)))
    await session.commit()


@pytest.fixture
async def desk(session: AsyncSession) -> AsyncIterator[Desk]:
    await _clear(session)

    student_role = await _role_with(
        session, "probe-student", ["ticket.view", "ticket.create", "ticket.reply"]
    )
    trainer_role = await _role_with(
        session,
        "probe-trainer",
        [
            "ticket.view",
            "ticket.create",
            "ticket.reply",
            "ticket.status",
            "ticket.escalate",
        ],
    )
    admin_role = await _role_with(
        session,
        "probe-admin",
        [
            "ticket.view",
            "ticket.view_all",
            "ticket.create",
            "ticket.reply",
            "ticket.assign",
            "ticket.status",
            "ticket.priority",
            "ticket.category",
            "ticket.escalate",
            "ticket.internal_note",
            "ticket.merge",
            "ticket.export",
            "ticket.report",
            "ticket.delete",
        ],
    )

    student = await _user_with_role(session, "student@probe.test", student_role)
    other_student = await _user_with_role(session, "other@probe.test", student_role)
    trainer = await _user_with_role(session, "trainer@probe.test", trainer_role)
    admin = await _user_with_role(session, "admin@probe.test", admin_role)
    await session.commit()

    # The grants went in through Core statements, so the instances still in
    # the identity map have never seen their roles. Detach everything and
    # load each person again, which is also what a real request does.
    identifiers = {
        "student": student.id,
        "other_student": other_student.id,
        "trainer": trainer.id,
        "admin": admin.id,
    }
    session.expunge_all()

    people = {
        key: await _load_user(session, user_id) for key, user_id in identifiers.items()
    }

    category = (
        await session.execute(
            select(Category)
            .join(CategoryType, Category.category_type_id == CategoryType.id)
            .where(CategoryType.slug == SUPPORT_TICKET_CATEGORY_TYPE_SLUG)
            .limit(1)
        )
    ).scalar_one()

    yield Desk(
        SupportTicketService(session),
        student=people["student"],
        other_student=people["other_student"],
        trainer=people["trainer"],
        admin=people["admin"],
        category=category,
    )

    await _clear(session)


async def _load_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Load a user with their roles and permissions eagerly attached."""
    user = await UserRepository(session).get(user_id)
    assert user is not None
    # Touch the property once, while the session is live, so a later read in
    # a synchronous policy check cannot trigger lazy IO.
    _ = user.permission_codes
    return user


def payload(subject: str = "Cannot open my course") -> TicketCreate:
    return TicketCreate(
        subject=subject,
        description="The player shows a spinner and never loads the lesson.",
    )


# -- Lifecycle rules (no database) ---------------------------------------


def test_status_transitions_follow_the_lifecycle() -> None:
    assert can_transition(TicketStatus.OPEN, TicketStatus.IN_PROGRESS)
    assert can_transition(TicketStatus.RESOLVED, TicketStatus.REOPENED)
    assert can_transition(TicketStatus.CLOSED, TicketStatus.REOPENED)
    # Restating the current status is a no-op, not an error.
    assert can_transition(TicketStatus.OPEN, TicketStatus.OPEN)

    # A finished ticket cannot be dragged back into the queue directly.
    assert not can_transition(TicketStatus.CLOSED, TicketStatus.IN_PROGRESS)
    assert not can_transition(TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS)
    # Nothing returns to `open`; `reopened` carries that meaning instead.
    assert not can_transition(TicketStatus.IN_PROGRESS, TicketStatus.OPEN)


# -- Creation and numbering ----------------------------------------------


async def test_ticket_numbers_are_sequential_and_dated(desk: Desk) -> None:
    first = await desk.service.create(payload(), actor=desk.student)
    second = await desk.service.create(payload("Second problem"), actor=desk.student)

    year = first.created_at.year
    assert first.ticket_no == f"TKT-{year}-000001"
    assert second.ticket_no == f"TKT-{year}-000002"


async def test_creating_a_ticket_opens_it_at_medium_priority(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    assert ticket.status == TicketStatus.OPEN
    assert ticket.priority == TicketPriority.MEDIUM
    assert ticket.student_id == desk.student.id
    assert ticket.total_replies == 0
    assert ticket.first_response_at is None


async def test_creation_writes_history_timeline_and_audit(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    history = await desk.service.status_history.list_for_ticket(ticket.id)
    assert [(h.old_status, h.new_status) for h in history] == [
        (None, TicketStatus.OPEN.value)
    ]

    timeline = await desk.service.activities.list_for_ticket(ticket.id)
    assert timeline[0].activity_type == "ticket_created"

    logs = (
        (
            await desk.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(ticket.id))
            )
        )
        .scalars()
        .all()
    )
    assert logs[-1].module == ActivityModule.SUPPORT
    assert logs[-1].entity_type == "SupportTicket"


async def test_a_ticket_rejects_a_category_from_another_taxonomy(
    desk: Desk, session: AsyncSession
) -> None:
    """A blog topic is a valid category, and still not a support topic.

    The taxonomy is built here rather than borrowed from whatever the
    database happens to hold, so the test proves the rule instead of
    skipping when the fixtures shift underneath it.
    """
    taxonomy = CategoryType(
        name="Probe Taxonomy", slug="probe-taxonomy", status="active"
    )
    session.add(taxonomy)
    await session.flush()

    foreign = Category(
        name="Probe Topic",
        slug="probe-topic",
        category_type_id=taxonomy.id,
        status="active",
    )
    session.add(foreign)
    await session.commit()

    try:
        with pytest.raises(BadRequestException):
            await desk.service.create(
                payload().model_copy(update={"category_id": foreign.id}),
                actor=desk.student,
            )
    finally:
        await session.execute(delete(Category).where(Category.id == foreign.id))
        await session.execute(
            delete(CategoryType).where(CategoryType.id == taxonomy.id)
        )
        await session.commit()


async def test_a_support_category_is_accepted(desk: Desk) -> None:
    ticket = await desk.service.create(
        payload().model_copy(update={"category_id": desk.category.id}),
        actor=desk.student,
    )

    assert ticket.category_id == desk.category.id


async def test_timeline_metadata_is_exposed_under_its_column_name(
    desk: Desk,
) -> None:
    """`metadata` is reserved on a declarative class but not in the API.

    The model maps the attribute as `activity_metadata` and the schema
    aliases it back, so a client sees the field the schema promises.
    """
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.change_priority(
        ticket.id,
        TicketPriorityChange(priority=TicketPriority.HIGH),
        actor=desk.admin,
    )

    entry = next(
        item
        for item in await desk.service.activities.list_for_ticket(ticket.id)
        if item.activity_type == "priority_changed"
    )

    rendered = ActivityRead.model_validate(entry)
    assert rendered.metadata is not None
    assert rendered.metadata["new"] == TicketPriority.HIGH.value

    body = rendered.model_dump(by_alias=True)
    assert "metadata" in body
    assert "activity_metadata" not in body


async def test_a_ticket_rejects_an_unknown_category(desk: Desk) -> None:
    with pytest.raises(ValidationException):
        await desk.service.create(
            payload().model_copy(update={"category_id": uuid.uuid4()}),
            actor=desk.student,
        )


# -- Scoping and visibility ----------------------------------------------


async def test_a_student_cannot_see_another_students_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    # 404, not 403: a 403 would confirm the ticket exists.
    with pytest.raises(NotFoundException):
        await desk.service.get(ticket.id, actor=desk.other_student)


async def test_listing_is_scoped_to_the_caller(desk: Desk) -> None:
    mine = await desk.service.create(payload("Mine"), actor=desk.student)
    theirs = await desk.service.create(payload("Theirs"), actor=desk.other_student)

    items, total = await desk.service.list_tickets(
        PaginationParams(page=1, page_size=50), actor=desk.student
    )
    assert total == 1
    assert items[0].id == mine.id

    items, total = await desk.service.list_tickets(
        PaginationParams(page=1, page_size=50), actor=desk.admin
    )
    assert total == 2
    assert {item.id for item in items} == {mine.id, theirs.id}


async def test_a_student_cannot_widen_their_scope_with_a_filter(desk: Desk) -> None:
    await desk.service.create(payload("Mine"), actor=desk.student)
    await desk.service.create(payload("Theirs"), actor=desk.other_student)

    # Asking for someone else's tickets narrows within your own slice, which
    # is empty - it never reaches across.
    _, total = await desk.service.list_tickets(
        PaginationParams(page=1, page_size=50),
        actor=desk.student,
        student_id=desk.other_student.id,
        scope=TicketScope.ALL,
    )
    assert total == 0


def test_scope_is_derived_from_permissions(desk: Desk) -> None:
    assert policy.scope_for(desk.student) is TicketScope.OWN
    assert policy.scope_for(desk.trainer) is TicketScope.ASSIGNED
    assert policy.scope_for(desk.admin) is TicketScope.ALL


# -- Replies --------------------------------------------------------------


async def test_a_staff_reply_stamps_first_response_once(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    await desk.service.reply(ticket.id, "Looking into it.", actor=desk.admin)
    ticket = await desk.service.get(ticket.id, actor=desk.admin)
    first = ticket.first_response_at

    assert first is not None
    assert ticket.total_replies == 1
    assert ticket.status == TicketStatus.WAITING_FOR_STUDENT

    await desk.service.reply(ticket.id, "Still looking.", actor=desk.admin)
    ticket = await desk.service.get(ticket.id, actor=desk.admin)

    # Answering again must not improve the response-time figure.
    assert ticket.first_response_at == first
    assert ticket.total_replies == 2


async def test_a_student_reply_moves_the_ticket_back_into_progress(
    desk: Desk,
) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.reply(ticket.id, "Any update?", actor=desk.student)

    ticket = await desk.service.get(ticket.id, actor=desk.student)
    assert ticket.status == TicketStatus.IN_PROGRESS
    assert ticket.first_response_at is None


async def test_a_student_reply_to_a_resolved_ticket_reopens_it(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.change_status(
        ticket.id, TicketStatusChange(status=TicketStatus.RESOLVED), actor=desk.admin
    )

    await desk.service.reply(ticket.id, "This is still broken.", actor=desk.student)
    ticket = await desk.service.get(ticket.id, actor=desk.student)

    assert ticket.status == TicketStatus.REOPENED


async def test_a_student_cannot_reply_to_someone_elses_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    with pytest.raises(NotFoundException):
        await desk.service.reply(ticket.id, "Me too.", actor=desk.other_student)


# -- Internal notes -------------------------------------------------------


async def test_internal_notes_are_hidden_from_the_student(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.reply(
        ticket.id, "Refund was already issued.", actor=desk.admin, is_internal_note=True
    )
    await desk.service.reply(ticket.id, "We are on it.", actor=desk.admin)

    student_view = await desk.service.list_messages(ticket.id, actor=desk.student)
    admin_view = await desk.service.list_messages(ticket.id, actor=desk.admin)

    assert all(not m.is_internal_note for m in student_view)
    assert any(m.is_internal_note for m in admin_view)
    assert "Refund was already issued." not in [m.message for m in student_view]


async def test_a_note_does_not_count_as_a_reply(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.reply(
        ticket.id, "Internal.", actor=desk.admin, is_internal_note=True
    )

    ticket = await desk.service.get(ticket.id, actor=desk.admin)
    assert ticket.total_replies == 0
    assert ticket.first_response_at is None


async def test_a_trainer_cannot_write_an_internal_note(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.assign(
        ticket.id, TicketAssign(assigned_to=desk.trainer.id), actor=desk.admin
    )

    with pytest.raises(ForbiddenException):
        await desk.service.reply(
            ticket.id, "Private.", actor=desk.trainer, is_internal_note=True
        )


# -- Assignment -----------------------------------------------------------


async def test_assigning_records_history_and_starts_the_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    ticket = await desk.service.assign(
        ticket.id,
        TicketAssign(assigned_to=desk.trainer.id, reason="Video specialist"),
        actor=desk.admin,
    )

    assert ticket.assigned_to == desk.trainer.id
    assert ticket.status == TicketStatus.IN_PROGRESS

    history = await desk.service.assignments.list_for_ticket(ticket.id)
    assert len(history) == 1
    assert history[0].assigned_from is None
    assert history[0].assigned_to == desk.trainer.id
    assert history[0].reason == "Video specialist"


async def test_reassignment_records_where_it_came_from(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.assign(
        ticket.id, TicketAssign(assigned_to=desk.trainer.id), actor=desk.admin
    )
    await desk.service.assign(
        ticket.id, TicketAssign(assigned_to=desk.admin.id), actor=desk.admin
    )

    history = await desk.service.assignments.list_for_ticket(ticket.id)
    assert len(history) == 2
    assert history[1].assigned_from == desk.trainer.id
    assert history[1].assigned_to == desk.admin.id


async def test_assigning_to_an_unknown_user_is_rejected(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    with pytest.raises(ValidationException):
        await desk.service.assign(
            ticket.id, TicketAssign(assigned_to=uuid.uuid4()), actor=desk.admin
        )


async def test_a_trainer_sees_only_their_assigned_queue(desk: Desk) -> None:
    mine = await desk.service.create(payload("Assigned"), actor=desk.student)
    await desk.service.create(payload("Not assigned"), actor=desk.other_student)
    await desk.service.assign(
        mine.id, TicketAssign(assigned_to=desk.trainer.id), actor=desk.admin
    )

    items, total = await desk.service.list_tickets(
        PaginationParams(page=1, page_size=50), actor=desk.trainer
    )
    assert total == 1
    assert items[0].id == mine.id


# -- Status, priority, escalation ----------------------------------------


async def test_an_illegal_status_move_is_refused(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.admin)

    with pytest.raises(BadRequestException):
        await desk.service.change_status(
            ticket.id,
            TicketStatusChange(status=TicketStatus.IN_PROGRESS),
            actor=desk.admin,
        )


async def test_resolving_stamps_resolved_at_and_records_history(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    ticket = await desk.service.change_status(
        ticket.id,
        TicketStatusChange(status=TicketStatus.RESOLVED, remarks="Cache cleared."),
        actor=desk.admin,
    )

    assert ticket.resolved_at is not None
    history = await desk.service.status_history.list_for_ticket(ticket.id)
    assert history[-1].new_status == TicketStatus.RESOLVED
    assert history[-1].remarks == "Cache cleared."


async def test_a_student_cannot_change_status(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    with pytest.raises(ForbiddenException):
        await desk.service.change_status(
            ticket.id,
            TicketStatusChange(status=TicketStatus.RESOLVED),
            actor=desk.student,
        )


async def test_priority_change_is_recorded(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    ticket = await desk.service.change_priority(
        ticket.id,
        TicketPriorityChange(priority=TicketPriority.URGENT),
        actor=desk.admin,
    )

    assert ticket.priority == TicketPriority.URGENT
    timeline = await desk.service.activities.list_for_ticket(ticket.id)
    assert any(entry.activity_type == "priority_changed" for entry in timeline)


async def test_escalation_flags_the_ticket_once(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    ticket = await desk.service.escalate(
        ticket.id,
        TicketEscalate(reason="Third time reported.", assigned_to=desk.admin.id),
        actor=desk.admin,
    )

    assert ticket.is_escalated is True
    assert ticket.status == TicketStatus.ESCALATED
    assert ticket.escalated_by == desk.admin.id
    assert ticket.assigned_to == desk.admin.id

    with pytest.raises(ConflictException):
        await desk.service.escalate(
            ticket.id, TicketEscalate(reason="Again."), actor=desk.admin
        )


async def test_a_reply_does_not_silently_clear_an_escalation(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.escalate(
        ticket.id, TicketEscalate(reason="Urgent."), actor=desk.admin
    )

    await desk.service.reply(ticket.id, "Investigating.", actor=desk.admin)
    ticket = await desk.service.get(ticket.id, actor=desk.admin)

    assert ticket.status == TicketStatus.ESCALATED


# -- Closing and reopening ------------------------------------------------


async def test_the_student_may_close_their_own_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    ticket = await desk.service.close(ticket.id, actor=desk.student)

    assert ticket.status == TicketStatus.CLOSED
    assert ticket.closed_at is not None
    # Closed without ever being resolved still resolved at that moment, or
    # the resolution-time report would skip it.
    assert ticket.resolved_at is not None


async def test_an_unrelated_trainer_cannot_close_a_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    # Not the assignee, and their scope does not reach the ticket at all.
    with pytest.raises(NotFoundException):
        await desk.service.close(ticket.id, actor=desk.trainer)


async def test_replying_to_a_closed_ticket_is_refused(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.student)

    with pytest.raises(BadRequestException):
        await desk.service.reply(ticket.id, "One more thing.", actor=desk.student)


async def test_reopening_clears_the_finished_timestamps(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.student)

    ticket = await desk.service.reopen(
        ticket.id, actor=desk.student, reason="Came back."
    )

    assert ticket.status == TicketStatus.REOPENED
    assert ticket.closed_at is None
    assert ticket.resolved_at is None


async def test_the_reopen_window_is_enforced_from_settings(
    desk: Desk, session: AsyncSession
) -> None:
    """A window of zero days means a closed ticket stays closed."""
    setting = (
        await session.execute(
            select(Setting).where(
                Setting.key == SupportSettingKey.REOPEN_WINDOW_DAYS.value
            )
        )
    ).scalar_one()
    original = setting.value
    setting.value = "0"
    await session.commit()

    try:
        ticket = await desk.service.create(payload(), actor=desk.student)
        await desk.service.close(ticket.id, actor=desk.student)

        # A fresh service, so the settings cache is not carrying the old value.
        service = SupportTicketService(session)
        with pytest.raises(BadRequestException):
            await service.reopen(ticket.id, actor=desk.student)
    finally:
        setting.value = original
        await session.commit()


# -- Feedback -------------------------------------------------------------


async def test_feedback_requires_a_finished_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    with pytest.raises(BadRequestException):
        await desk.service.submit_feedback(
            ticket.id, FeedbackCreate(rating=5), actor=desk.student
        )


async def test_feedback_is_recorded_once_and_mirrored(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.student)

    await desk.service.submit_feedback(
        ticket.id,
        FeedbackCreate(rating=4, feedback="Sorted quickly."),
        actor=desk.student,
    )

    ticket = await desk.service.get(ticket.id, actor=desk.student)
    assert ticket.satisfaction_rating == 4
    assert ticket.satisfaction_comment == "Sorted quickly."

    with pytest.raises(ConflictException):
        await desk.service.submit_feedback(
            ticket.id, FeedbackCreate(rating=1), actor=desk.student
        )


async def test_only_the_student_may_rate_a_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.student)

    with pytest.raises(ForbiddenException):
        await desk.service.submit_feedback(
            ticket.id, FeedbackCreate(rating=5), actor=desk.admin
        )


# -- Merging --------------------------------------------------------------


async def test_merging_moves_the_conversation_and_keeps_the_duplicate(
    desk: Desk,
) -> None:
    duplicate = await desk.service.create(payload("Duplicate"), actor=desk.student)
    survivor = await desk.service.create(payload("Original"), actor=desk.student)
    await desk.service.reply(duplicate.id, "Extra detail.", actor=desk.student)

    target = await desk.service.merge(
        duplicate.id,
        TicketMerge(target_ticket_id=survivor.id, reason="Same problem."),
        actor=desk.admin,
    )

    assert target.id == survivor.id

    duplicate = await desk.service.get(duplicate.id, actor=desk.admin)
    assert duplicate.merged_into_id == survivor.id
    assert duplicate.status == TicketStatus.CLOSED

    moved = await desk.service.messages.list_for_ticket(
        survivor.id, include_internal=True
    )
    assert any(message.message == "Extra detail." for message in moved)


async def test_a_ticket_cannot_be_merged_into_itself(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    with pytest.raises(BadRequestException):
        await desk.service.merge(
            ticket.id, TicketMerge(target_ticket_id=ticket.id), actor=desk.admin
        )


# -- Editing and deletion -------------------------------------------------


async def test_a_student_cannot_edit_a_closed_ticket(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)
    await desk.service.close(ticket.id, actor=desk.student)

    with pytest.raises(BadRequestException):
        await desk.service.update(
            ticket.id, TicketUpdate(subject="Rewritten"), actor=desk.student
        )


async def test_soft_delete_and_restore(desk: Desk) -> None:
    ticket = await desk.service.create(payload(), actor=desk.student)

    await desk.service.delete(ticket.id, actor=desk.admin)
    with pytest.raises(NotFoundException):
        await desk.service.get(ticket.id, actor=desk.admin)

    restored = await desk.service.restore(ticket.id, actor=desk.admin)
    assert restored.deleted_at is None


# -- Admin creation, statistics and export -------------------------------


async def test_an_agent_can_raise_a_ticket_for_a_student(desk: Desk) -> None:
    ticket = await desk.service.create_for_student(
        AdminTicketCreate(
            subject="Reported by phone",
            description="Learner cannot reach the live class.",
            student_id=desk.student.id,
            priority=TicketPriority.HIGH,
            assigned_to=desk.trainer.id,
        ),
        actor=desk.admin,
    )

    assert ticket.student_id == desk.student.id
    assert ticket.created_by == desk.admin.id
    assert ticket.priority == TicketPriority.HIGH
    assert ticket.assigned_to == desk.trainer.id


async def test_statistics_count_the_queue(desk: Desk, session: AsyncSession) -> None:
    open_ticket = await desk.service.create(payload("Open one"), actor=desk.student)
    resolved = await desk.service.create(payload("Resolved one"), actor=desk.student)
    await desk.service.change_status(
        resolved.id, TicketStatusChange(status=TicketStatus.RESOLVED), actor=desk.admin
    )
    await desk.service.escalate(
        open_ticket.id, TicketEscalate(reason="Loud."), actor=desk.admin
    )

    stats = await SupportStatsService(session).dashboard()

    assert stats.total_tickets == 2
    assert stats.resolved_tickets == 1
    assert stats.open_tickets == 1
    assert stats.escalated_tickets == 1
    assert sum(item.count for item in stats.by_priority) == 2


async def test_average_response_time_is_null_before_any_reply(
    desk: Desk, session: AsyncSession
) -> None:
    await desk.service.create(payload(), actor=desk.student)

    stats = await SupportStatsService(session).dashboard()
    assert stats.average_response_seconds is None
    assert stats.average_response_hours is None


async def test_export_produces_a_csv_of_the_scoped_queue(
    desk: Desk, session: AsyncSession
) -> None:
    ticket = await desk.service.create(payload("Exported"), actor=desk.student)

    body = await SupportExportService(session).export_csv(actor=desk.admin)
    lines = body.strip().splitlines()

    assert lines[0].startswith('"ticket_no"')
    assert ticket.ticket_no in body
    assert len(lines) == 2


async def test_export_quotes_a_subject_containing_a_comma(
    desk: Desk, session: AsyncSession
) -> None:
    await desk.service.create(
        payload("Payment failed, twice, today"), actor=desk.student
    )

    body = await SupportExportService(session).export_csv(actor=desk.admin)

    assert '"Payment failed, twice, today"' in body
    assert len(body.strip().splitlines()) == 2
