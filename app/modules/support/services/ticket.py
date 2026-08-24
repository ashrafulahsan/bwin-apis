"""Business logic for support tickets.

The service owns the transaction: every public method that changes something
commits once, after the change, its history rows and its audit entry have all
been written. Authorization is applied here too, against the ticket in hand,
because a route guard can only say what a role may do in general - not
whether *this* ticket is theirs.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.settings.services.setting import SettingService
from app.modules.support import policy
from app.modules.support.constants import (
    DEFAULT_REOPEN_WINDOW_DAYS,
    SUPPORT_TICKET_CATEGORY_TYPE_SLUG,
    TERMINAL_STATUSES,
    TICKET_SEARCH_FIELDS,
    SupportSettingKey,
    TicketActivityType,
    TicketPriority,
    TicketStatus,
    can_transition,
)
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.models.support_ticket_message import SupportTicketMessage
from app.modules.support.permissions import SupportPermission
from app.modules.support.policy import TicketScope
from app.modules.support.repositories.attachment import (
    SupportTicketAttachmentRepository,
)
from app.modules.support.repositories.message import (
    SupportTicketActivityRepository,
    SupportTicketAssignmentRepository,
    SupportTicketFeedbackRepository,
    SupportTicketMessageRepository,
    SupportTicketStatusHistoryRepository,
)
from app.modules.support.repositories.ticket import SupportTicketRepository
from app.modules.support.schemas.ticket import (
    AdminTicketCreate,
    FeedbackCreate,
    TicketAssign,
    TicketCategoryChange,
    TicketCreate,
    TicketEscalate,
    TicketMerge,
    TicketPriorityChange,
    TicketStatusChange,
    TicketUpdate,
)
from app.modules.users.models.user import User
from app.modules.users.repositories.user import UserRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.dates import utc_now


class SupportTicketService:
    """Coordinates the support desk: raising, working and closing tickets."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SupportTicketRepository(session)
        self.messages = SupportTicketMessageRepository(session)
        self.attachments = SupportTicketAttachmentRepository(session)
        self.assignments = SupportTicketAssignmentRepository(session)
        self.status_history = SupportTicketStatusHistoryRepository(session)
        self.activities = SupportTicketActivityRepository(session)
        self.feedback = SupportTicketFeedbackRepository(session)
        self.categories = CategoryRepository(session)
        self.users = UserRepository(session)
        self.settings = SettingService(session)
        self.activity = ActivityLogService(session, ActivityModule.SUPPORT)

        # Imported lazily to keep the module import graph acyclic: the
        # timeline writer knows nothing about this service.
        from app.modules.support.services.timeline import TicketTimeline

        self.timeline = TicketTimeline(session)

    # -- Reads ------------------------------------------------------------

    async def get(self, ticket_id: uuid.UUID, *, actor: User) -> SupportTicket:
        """Fetch a ticket the caller is entitled to see.

        A ticket outside the caller's scope comes back as 404 rather than
        403. A 403 would confirm that a ticket with that id exists, which is
        an information leak in a system where ids are the only thing standing
        between one student and another's support history.
        """
        ticket = await self.repository.get_or_raise(ticket_id)

        if not policy.can_view_ticket(actor, ticket):
            raise NotFoundException("SupportTicket")

        return ticket

    async def get_by_ticket_no(self, ticket_no: str, *, actor: User) -> SupportTicket:
        ticket = await self.repository.get_by_ticket_no(ticket_no)
        if ticket is None or not policy.can_view_ticket(actor, ticket):
            raise NotFoundException(f"Ticket '{ticket_no}'")
        return ticket

    async def list_tickets(
        self,
        pagination: SupportsPagination,
        *,
        actor: User,
        search: str | None = None,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        category_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
        assigned_to: uuid.UUID | None = None,
        is_escalated: bool | None = None,
        unassigned: bool = False,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        scope: TicketScope | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[SupportTicket], int]:
        """One listing, narrowed by the caller's scope before any filter.

        The scope clause is added first and cannot be overridden by a query
        parameter: passing `student_id=<someone else>` narrows within what
        the caller may already see, it never widens it.
        """
        filters = self._scope_filters(actor, scope)

        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if priority is not None:
            filters.append(Filter.eq("priority", priority.value))
        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if student_id is not None:
            filters.append(Filter.eq("student_id", student_id))
        if assigned_to is not None:
            filters.append(Filter.eq("assigned_to", assigned_to))
        if is_escalated is not None:
            filters.append(Filter.eq("is_escalated", is_escalated))
        if unassigned:
            filters.append(Filter.is_null("assigned_to"))
        if date_from is not None:
            filters.append(Filter.gte("created_at", date_from))
        if date_to is not None:
            filters.append(Filter.lte("created_at", date_to))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(TICKET_SEARCH_FIELDS),
            sort_by=sort_by or "created_at",
            sort_order=sort_order,
        )

    def _scope_filters(
        self, actor: User, scope: TicketScope | None = None
    ) -> list[Filter]:
        """Translate the caller's scope into WHERE clauses.

        `scope` may narrow what the caller is entitled to - the trainer's
        "my tickets" view asks for `ASSIGNED` explicitly - but the widest it
        can reach is still whatever `policy.scope_for` allows.
        """
        allowed = policy.scope_for(actor)
        effective = scope if scope is not None else allowed

        # Never let a requested scope exceed the granted one.
        if allowed is TicketScope.OWN:
            effective = TicketScope.OWN
        elif allowed is TicketScope.ASSIGNED and effective is TicketScope.ALL:
            effective = TicketScope.ASSIGNED

        if effective is TicketScope.ALL:
            return []
        if effective is TicketScope.ASSIGNED:
            return [Filter.eq("assigned_to", actor.id)]

        return [Filter.eq("student_id", actor.id)]

    async def get_detail(self, ticket_id: uuid.UUID, *, actor: User) -> dict[str, Any]:
        """Everything one ticket page renders, with internal notes filtered.

        The visibility decision is made once, here, and applied to both the
        thread and the timeline. Two separate decisions is how a note leaks.
        """
        ticket = await self.get(ticket_id, actor=actor)
        include_internal = policy.can_see_internal_notes(actor)

        return {
            "ticket": ticket,
            "messages": await self.messages.list_for_ticket(
                ticket.id, include_internal=include_internal
            ),
            "attachments": await self.attachments.list_for_ticket(ticket.id),
            "activities": await self.activities.list_for_ticket(ticket.id),
            "status_history": await self.status_history.list_for_ticket(ticket.id),
            "assignments": (
                await self.assignments.list_for_ticket(ticket.id)
                if policy.is_staff(actor)
                else []
            ),
            "feedback": await self.feedback.get_for_ticket(ticket.id),
        }

    async def list_messages(
        self, ticket_id: uuid.UUID, *, actor: User
    ) -> list[SupportTicketMessage]:
        ticket = await self.get(ticket_id, actor=actor)
        return await self.messages.list_for_ticket(
            ticket.id, include_internal=policy.can_see_internal_notes(actor)
        )

    # -- Creating ---------------------------------------------------------

    async def create(
        self, payload: TicketCreate, *, actor: User, student_id: uuid.UUID | None = None
    ) -> SupportTicket:
        """Raise a ticket.

        Opens at medium priority regardless of who files it, because the
        priority a requester assigns to their own problem is always urgent.
        An agent filing on someone's behalf can set it afterwards through the
        priority route, which is audited.
        """
        owner_id = student_id or actor.id

        if owner_id != actor.id:
            await self._require_known_user(owner_id, role="student")

        await self._validate_category(payload.category_id)

        now = utc_now()
        ticket_no = await self.repository.next_ticket_no(now.year)

        ticket = await self.repository.create(
            ticket_no=ticket_no,
            subject=payload.subject,
            description=payload.description,
            category_id=payload.category_id,
            student_id=owner_id,
            priority=TicketPriority.MEDIUM.value,
            status=TicketStatus.OPEN.value,
            source=payload.source.value,
            created_by=actor.id,
            updated_by=actor.id,
        )

        await self.timeline.status_change(
            ticket,
            old_status=None,
            new_status=TicketStatus.OPEN.value,
            actor_id=actor.id,
            remarks="Ticket raised.",
        )
        await self.timeline.activity(
            ticket,
            TicketActivityType.CREATED,
            f"Ticket {ticket.ticket_no} was created.",
            actor_id=actor.id,
            metadata={"subject": ticket.subject, "source": ticket.source},
        )
        await self.activity.record(
            ActivityAction.CREATE,
            entity=ticket,
            description=f"Created support ticket {ticket.ticket_no}",
            new_values=snapshot(ticket),
        )

        await self.session.commit()
        return ticket

    async def create_for_student(
        self, payload: AdminTicketCreate, *, actor: User
    ) -> SupportTicket:
        """An agent raising a ticket on a student's behalf.

        Priority and assignment are applied after creation rather than at
        insert, so both go through the audited routes and land in the history
        tables like any other change.
        """
        ticket = await self.create(payload, actor=actor, student_id=payload.student_id)

        if payload.priority is not TicketPriority.MEDIUM:
            ticket = await self.change_priority(
                ticket.id,
                TicketPriorityChange(priority=payload.priority),
                actor=actor,
            )
        if payload.assigned_to is not None:
            ticket = await self.assign(
                ticket.id,
                TicketAssign(assigned_to=payload.assigned_to),
                actor=actor,
            )

        return ticket

    async def update(
        self, ticket_id: uuid.UUID, payload: TicketUpdate, *, actor: User
    ) -> SupportTicket:
        """Edit the ticket's own text.

        The student may correct their own wording while the ticket is still
        open; staff may edit at any point. A finished ticket is left alone -
        rewriting the question after it has been answered makes the thread
        incoherent.
        """
        ticket = await self.get(ticket_id, actor=actor)

        if not policy.is_staff(actor):
            if not policy.is_owner(actor, ticket):
                raise ForbiddenException("You may only edit your own tickets.")
            if not ticket.is_open:
                raise BadRequestException(
                    "This ticket is closed and can no longer be edited."
                )

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return ticket

        if "category_id" in changes:
            await self._validate_category(changes["category_id"])

        changes["updated_by"] = actor.id

        before = snapshot(ticket, fields=changes.keys())
        updated = await self.repository.update(ticket, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated support ticket {updated.ticket_no}",
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    # -- Conversation -----------------------------------------------------

    async def reply(
        self,
        ticket_id: uuid.UUID,
        message: str,
        *,
        actor: User,
        is_internal_note: bool = False,
    ) -> SupportTicketMessage:
        """Add a message to the thread.

        Replying to a resolved ticket reopens it: a student writing back has
        not accepted the resolution, and leaving the ticket resolved would
        drop their reply out of every queue. A closed ticket is not reopened
        this way - that goes through `reopen`, which enforces the window.
        """
        ticket = await self.get(ticket_id, actor=actor)

        if is_internal_note:
            if not policy.can_see_internal_notes(actor):
                raise ForbiddenException(
                    "Writing an internal note requires the "
                    f"'{SupportPermission.INTERNAL_NOTE}' permission."
                )
        elif not policy.can_reply_to(actor, ticket):
            raise ForbiddenException("You may not reply to this ticket.")

        if ticket.is_closed and not is_internal_note:
            raise BadRequestException(
                "This ticket is closed. Reopen it before replying."
            )

        now = utc_now()
        entry = await self.messages.create(
            ticket_id=ticket.id,
            user_id=actor.id,
            message=message,
            is_internal_note=is_internal_note,
            is_system_message=False,
            created_by=actor.id,
            updated_by=actor.id,
        )

        if is_internal_note:
            await self.timeline.activity(
                ticket,
                TicketActivityType.INTERNAL_NOTE_ADDED,
                f"{actor.full_name} added an internal note.",
                actor_id=actor.id,
                metadata={"message_id": entry.id},
            )
            await self.activity.record(
                ActivityAction.REPLY,
                entity=ticket,
                description=f"Added an internal note to {ticket.ticket_no}",
                new_values={"message_id": str(entry.id), "internal": True},
            )
            await self.session.commit()
            return entry

        changes: dict[str, Any] = {"last_reply_at": now, "updated_by": actor.id}

        is_staff_reply = not policy.is_owner(actor, ticket)
        if is_staff_reply and ticket.first_response_at is None:
            changes["first_response_at"] = now

        # A reply moves the ball to the other side, so the queue reflects who
        # is being waited on without anyone setting a status by hand.
        next_status = self._status_after_reply(ticket, is_staff_reply=is_staff_reply)
        previous_status = ticket.status
        if next_status is not None:
            changes["status"] = next_status.value

        await self.repository.update(ticket, **changes)
        await self.repository.bump_counters(ticket, replies=1)

        if next_status is not None and next_status.value != previous_status:
            await self._record_status_move(
                ticket,
                old_status=previous_status,
                new_status=next_status.value,
                actor=actor,
                remarks="Automatic: a reply was added.",
            )

        await self.timeline.activity(
            ticket,
            TicketActivityType.REPLY_ADDED,
            f"{actor.full_name} replied.",
            actor_id=actor.id,
            metadata={"message_id": entry.id},
        )
        await self.activity.record(
            ActivityAction.REPLY,
            entity=ticket,
            description=f"Replied to support ticket {ticket.ticket_no}",
            new_values={"message_id": str(entry.id), "internal": False},
        )

        await self.session.commit()
        return entry

    @staticmethod
    def _status_after_reply(
        ticket: SupportTicket, *, is_staff_reply: bool
    ) -> TicketStatus | None:
        """Where a reply leaves the ticket, or `None` to leave it alone.

        Escalated tickets are never moved automatically: an escalation is a
        deliberate flag and only a deliberate act should clear it.
        """
        current = TicketStatus(ticket.status)

        if current is TicketStatus.ESCALATED:
            return None
        if current is TicketStatus.RESOLVED:
            # The student did not accept the resolution.
            return None if is_staff_reply else TicketStatus.REOPENED

        return (
            TicketStatus.WAITING_FOR_STUDENT
            if is_staff_reply
            else TicketStatus.IN_PROGRESS
        )

    # -- Workflow ---------------------------------------------------------

    async def assign(
        self, ticket_id: uuid.UUID, payload: TicketAssign, *, actor: User
    ) -> SupportTicket:
        """Hand a ticket to an agent, or return it to the pool."""
        ticket = await self.get(ticket_id, actor=actor)

        if payload.assigned_to is not None:
            await self._require_known_user(payload.assigned_to, role="agent")

        previous = ticket.assigned_to
        if previous == payload.assigned_to:
            return ticket

        changes: dict[str, Any] = {
            "assigned_to": payload.assigned_to,
            "updated_by": actor.id,
        }

        # Picking up an untouched ticket starts the clock on it.
        if payload.assigned_to is not None and ticket.status == TicketStatus.OPEN:
            changes["status"] = TicketStatus.IN_PROGRESS.value

        previous_status = ticket.status
        await self.repository.update(ticket, **changes)

        await self.timeline.assignment(
            ticket,
            assigned_from=previous,
            assigned_to=payload.assigned_to,
            actor_id=actor.id,
            reason=payload.reason,
        )

        if changes.get("status") and changes["status"] != previous_status:
            await self._record_status_move(
                ticket,
                old_status=previous_status,
                new_status=changes["status"],
                actor=actor,
                remarks="Automatic: the ticket was assigned.",
            )

        is_reassignment = previous is not None
        assignee_name = await self._name_of(payload.assigned_to)
        description = (
            f"Reassigned to {assignee_name}."
            if is_reassignment and payload.assigned_to is not None
            else (
                f"Assigned to {assignee_name}."
                if payload.assigned_to is not None
                else "Returned to the unassigned queue."
            )
        )

        await self.timeline.activity(
            ticket,
            (
                TicketActivityType.REASSIGNED
                if is_reassignment
                else TicketActivityType.ASSIGNED
            ),
            description,
            actor_id=actor.id,
            metadata={"assigned_from": previous, "assigned_to": payload.assigned_to},
        )
        await self.timeline.system_message(ticket, description, actor_id=actor.id)
        await self.activity.record(
            ActivityAction.REASSIGN if is_reassignment else ActivityAction.ASSIGN,
            entity=ticket,
            description=f"{description[:-1]} on ticket {ticket.ticket_no}",
            old_values={"assigned_to": str(previous) if previous else None},
            new_values={
                "assigned_to": (
                    str(payload.assigned_to) if payload.assigned_to else None
                )
            },
        )

        await self.session.commit()
        return ticket

    async def change_status(
        self, ticket_id: uuid.UUID, payload: TicketStatusChange, *, actor: User
    ) -> SupportTicket:
        """Move a ticket through the lifecycle, honouring the transition map."""
        ticket = await self.get(ticket_id, actor=actor)
        target = payload.status

        if target is TicketStatus.CLOSED:
            return await self.close(ticket_id, remarks=payload.remarks, actor=actor)
        if target is TicketStatus.REOPENED:
            return await self.reopen(ticket_id, reason=payload.remarks, actor=actor)

        if not policy.is_staff(actor):
            raise ForbiddenException("Only staff may change a ticket's status.")

        current = TicketStatus(ticket.status)
        if current is target:
            return ticket

        if not can_transition(current, target):
            raise BadRequestException(
                f"A ticket cannot move from '{current.value}' to '{target.value}'."
            )

        changes: dict[str, Any] = {"status": target.value, "updated_by": actor.id}
        if target is TicketStatus.RESOLVED:
            changes["resolved_at"] = utc_now()
        if target is TicketStatus.ESCALATED:
            changes["is_escalated"] = True
            changes["escalated_at"] = utc_now()
            changes["escalated_by"] = actor.id

        await self.repository.update(ticket, **changes)
        await self._record_status_move(
            ticket,
            old_status=current.value,
            new_status=target.value,
            actor=actor,
            remarks=payload.remarks,
        )

        await self.session.commit()
        return ticket

    async def change_priority(
        self, ticket_id: uuid.UUID, payload: TicketPriorityChange, *, actor: User
    ) -> SupportTicket:
        ticket = await self.get(ticket_id, actor=actor)
        previous = ticket.priority

        if previous == payload.priority.value:
            return ticket

        await self.repository.update(
            ticket, priority=payload.priority.value, updated_by=actor.id
        )

        description = f"Priority changed from {previous} to {payload.priority.value}."
        await self.timeline.activity(
            ticket,
            TicketActivityType.PRIORITY_CHANGED,
            description,
            actor_id=actor.id,
            metadata={
                "old": previous,
                "new": payload.priority.value,
                "reason": payload.reason,
            },
        )
        await self.activity.record(
            ActivityAction.UPDATE,
            entity=ticket,
            description=f"{description[:-1]} on ticket {ticket.ticket_no}",
            old_values={"priority": previous},
            new_values={"priority": payload.priority.value},
        )

        await self.session.commit()
        return ticket

    async def change_category(
        self, ticket_id: uuid.UUID, payload: TicketCategoryChange, *, actor: User
    ) -> SupportTicket:
        ticket = await self.get(ticket_id, actor=actor)
        previous = ticket.category_id

        if previous == payload.category_id:
            return ticket

        await self._validate_category(payload.category_id)
        await self.repository.update(
            ticket, category_id=payload.category_id, updated_by=actor.id
        )

        description = (
            f"Category changed to {await self._category_name(payload.category_id)}."
        )
        await self.timeline.activity(
            ticket,
            TicketActivityType.CATEGORY_CHANGED,
            description,
            actor_id=actor.id,
            metadata={
                "old": previous,
                "new": payload.category_id,
                "reason": payload.reason,
            },
        )
        await self.activity.record(
            ActivityAction.UPDATE,
            entity=ticket,
            description=f"Recategorised ticket {ticket.ticket_no}",
            old_values={"category_id": str(previous) if previous else None},
            new_values={
                "category_id": str(payload.category_id) if payload.category_id else None
            },
        )

        await self.session.commit()
        return ticket

    async def escalate(
        self, ticket_id: uuid.UUID, payload: TicketEscalate, *, actor: User
    ) -> SupportTicket:
        """Flag a ticket for attention above the assigned agent."""
        ticket = await self.get(ticket_id, actor=actor)

        if TicketStatus(ticket.status) in TERMINAL_STATUSES:
            raise BadRequestException("A finished ticket cannot be escalated.")
        if ticket.is_escalated:
            raise ConflictException("This ticket has already been escalated.")

        now = utc_now()
        previous_status = ticket.status
        changes: dict[str, Any] = {
            "is_escalated": True,
            "escalated_at": now,
            "escalated_by": actor.id,
            "escalation_reason": payload.reason,
            "status": TicketStatus.ESCALATED.value,
            "updated_by": actor.id,
        }
        if payload.assigned_to is not None:
            await self._require_known_user(payload.assigned_to, role="agent")
            changes["assigned_to"] = payload.assigned_to

        previous_assignee = ticket.assigned_to
        await self.repository.update(ticket, **changes)

        if payload.assigned_to is not None and payload.assigned_to != previous_assignee:
            await self.timeline.assignment(
                ticket,
                assigned_from=previous_assignee,
                assigned_to=payload.assigned_to,
                actor_id=actor.id,
                reason="Escalation.",
            )

        await self._record_status_move(
            ticket,
            old_status=previous_status,
            new_status=TicketStatus.ESCALATED.value,
            actor=actor,
            remarks=payload.reason,
            activity_type=TicketActivityType.ESCALATED,
            description=f"Escalated by {actor.full_name}.",
        )
        await self.activity.record(
            ActivityAction.ESCALATE,
            entity=ticket,
            description=f"Escalated support ticket {ticket.ticket_no}",
            new_values={"reason": payload.reason},
        )

        await self.session.commit()
        return ticket

    async def close(
        self, ticket_id: uuid.UUID, *, actor: User, remarks: str | None = None
    ) -> SupportTicket:
        """Close a ticket. Open to the student, the assignee, and admins."""
        ticket = await self.get(ticket_id, actor=actor)

        if not policy.can_close(actor, ticket):
            raise ForbiddenException(
                "Only the student, the assigned agent or an administrator may "
                "close this ticket."
            )
        if ticket.is_closed:
            raise ConflictException("This ticket is already closed.")

        now = utc_now()
        previous_status = ticket.status
        changes: dict[str, Any] = {
            "status": TicketStatus.CLOSED.value,
            "closed_at": now,
            "updated_by": actor.id,
        }
        # A ticket closed without ever being marked resolved still resolved
        # at that moment; the resolution-time report depends on it.
        if ticket.resolved_at is None:
            changes["resolved_at"] = now

        await self.repository.update(ticket, **changes)
        await self._record_status_move(
            ticket,
            old_status=previous_status,
            new_status=TicketStatus.CLOSED.value,
            actor=actor,
            remarks=remarks,
            activity_type=TicketActivityType.CLOSED,
            description=f"Closed by {actor.full_name}.",
        )
        await self.activity.record(
            ActivityAction.CLOSE,
            entity=ticket,
            description=f"Closed support ticket {ticket.ticket_no}",
            old_values={"status": previous_status},
            new_values={"status": TicketStatus.CLOSED.value},
        )

        await self.session.commit()
        return ticket

    async def reopen(
        self, ticket_id: uuid.UUID, *, actor: User, reason: str | None = None
    ) -> SupportTicket:
        """Reopen a finished ticket, inside the configured window.

        The window is counted from `closed_at`, which is the moment the
        student stopped being able to reply - not from the last update, which
        an agent tidying up afterwards would push forward.
        """
        ticket = await self.get(ticket_id, actor=actor)

        if not policy.can_reopen(actor, ticket):
            raise ForbiddenException("You may not reopen this ticket.")
        if TicketStatus(ticket.status) not in TERMINAL_STATUSES:
            raise BadRequestException("This ticket is not closed.")

        await self._require_within_reopen_window(ticket)

        previous_status = ticket.status
        await self.repository.update(
            ticket,
            status=TicketStatus.REOPENED.value,
            closed_at=None,
            resolved_at=None,
            updated_by=actor.id,
        )
        await self._record_status_move(
            ticket,
            old_status=previous_status,
            new_status=TicketStatus.REOPENED.value,
            actor=actor,
            remarks=reason,
            activity_type=TicketActivityType.REOPENED,
            description=f"Reopened by {actor.full_name}.",
        )
        await self.activity.record(
            ActivityAction.REOPEN,
            entity=ticket,
            description=f"Reopened support ticket {ticket.ticket_no}",
            old_values={"status": previous_status},
            new_values={"status": TicketStatus.REOPENED.value, "reason": reason},
        )

        await self.session.commit()
        return ticket

    async def _require_within_reopen_window(self, ticket: SupportTicket) -> None:
        """Refuse a reopen that arrives too late.

        A window of zero days is read as "never reopen"; a negative value as
        "no limit", which is the escape hatch for a desk that does not want
        the rule at all.
        """
        days = await self.settings.number(
            SupportSettingKey.REOPEN_WINDOW_DAYS, DEFAULT_REOPEN_WINDOW_DAYS
        )
        if days < 0:
            return

        reference = ticket.closed_at or ticket.resolved_at
        if reference is None:
            return

        deadline = reference + timedelta(days=days)
        if utc_now() > deadline:
            raise BadRequestException(
                f"This ticket was closed more than {days} day(s) ago and can no "
                "longer be reopened. Please raise a new ticket."
            )

    async def merge(
        self, ticket_id: uuid.UUID, payload: TicketMerge, *, actor: User
    ) -> SupportTicket:
        """Fold a duplicate into the ticket that should carry the conversation.

        The duplicate is kept rather than deleted: its number has been quoted
        to the student, and a reference that resolves to nothing is worse
        than one that says where the conversation went.
        """
        source = await self.get(ticket_id, actor=actor)
        target = await self.repository.get_or_raise(payload.target_ticket_id)

        if source.id == target.id:
            raise BadRequestException("A ticket cannot be merged into itself.")
        if source.is_merged:
            raise ConflictException(
                f"Ticket {source.ticket_no} has already been merged."
            )
        if target.is_merged:
            raise BadRequestException(
                f"Ticket {target.ticket_no} is itself merged into another ticket."
            )

        moved = await self.messages.reassign_to_ticket(source.id, target.id)
        attachments = await self.attachments.list_for_ticket(source.id)
        for attachment in attachments:
            attachment.ticket_id = target.id
        await self.session.flush()

        now = utc_now()
        await self.repository.update(
            source,
            merged_into_id=target.id,
            merged_at=now,
            status=TicketStatus.CLOSED.value,
            closed_at=source.closed_at or now,
            resolved_at=source.resolved_at or now,
            updated_by=actor.id,
        )
        await self.repository.bump_counters(
            target, replies=moved, attachments=len(attachments)
        )

        await self.timeline.status_change(
            source,
            old_status=source.status,
            new_status=TicketStatus.CLOSED.value,
            actor_id=actor.id,
            remarks=f"Merged into {target.ticket_no}.",
        )
        await self.timeline.activity(
            source,
            TicketActivityType.MERGED,
            f"Merged into ticket {target.ticket_no}.",
            actor_id=actor.id,
            metadata={"target_ticket_id": target.id, "reason": payload.reason},
        )
        await self.timeline.activity(
            target,
            TicketActivityType.MERGED,
            f"Ticket {source.ticket_no} was merged into this one.",
            actor_id=actor.id,
            metadata={
                "source_ticket_id": source.id,
                "messages_moved": moved,
                "attachments_moved": len(attachments),
            },
        )
        await self.activity.record(
            ActivityAction.MERGE,
            entity=source,
            description=(f"Merged ticket {source.ticket_no} into {target.ticket_no}"),
            new_values={
                "target_ticket_id": str(target.id),
                "messages_moved": moved,
                "attachments_moved": len(attachments),
            },
        )

        await self.session.commit()
        return target

    # -- Feedback ---------------------------------------------------------

    async def submit_feedback(
        self, ticket_id: uuid.UUID, payload: FeedbackCreate, *, actor: User
    ) -> Any:
        """Record the satisfaction survey, once, after the ticket is finished."""
        ticket = await self.get(ticket_id, actor=actor)

        if not policy.is_owner(actor, ticket):
            raise ForbiddenException(
                "Only the student who raised a ticket may rate it."
            )
        if TicketStatus(ticket.status) not in TERMINAL_STATUSES:
            raise BadRequestException(
                "Feedback can only be given once a ticket is resolved or closed."
            )
        if await self.feedback.exists_for_ticket(ticket.id):
            raise ConflictException("Feedback has already been given for this ticket.")

        entry = await self.feedback.create(
            ticket_id=ticket.id,
            rating=payload.rating,
            feedback=payload.feedback,
            submitted_by=actor.id,
        )
        # Mirrored onto the ticket so a queue listing can show the score
        # without joining; the row above stays the record of when and by whom.
        await self.repository.update(
            ticket,
            satisfaction_rating=payload.rating,
            satisfaction_comment=payload.feedback,
            updated_by=actor.id,
        )

        await self.timeline.activity(
            ticket,
            TicketActivityType.FEEDBACK_SUBMITTED,
            f"Rated {payload.rating} out of 5.",
            actor_id=actor.id,
            metadata={"rating": payload.rating},
        )
        await self.activity.record(
            ActivityAction.FEEDBACK,
            entity=ticket,
            description=f"Rated support ticket {ticket.ticket_no}",
            new_values={"rating": payload.rating},
        )

        await self.session.commit()
        return entry

    # -- Deletion ---------------------------------------------------------

    async def delete(self, ticket_id: uuid.UUID, *, actor: User) -> None:
        """Soft delete, keeping the ticket for audit and restore."""
        ticket = await self.repository.get_or_raise(ticket_id)
        before = snapshot(ticket)

        await self.repository.soft_delete(ticket)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=ticket,
            description=f"Deleted support ticket {ticket.ticket_no}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, ticket_id: uuid.UUID, *, actor: User) -> SupportTicket:
        ticket = await self.repository.get_or_raise(ticket_id, include_deleted=True)
        restored = await self.repository.restore(ticket)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored support ticket {restored.ticket_no}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    # -- Internals --------------------------------------------------------

    async def _record_status_move(
        self,
        ticket: SupportTicket,
        *,
        old_status: str | None,
        new_status: str,
        actor: User,
        remarks: str | None = None,
        activity_type: TicketActivityType = TicketActivityType.STATUS_CHANGED,
        description: str | None = None,
    ) -> None:
        """Write the history row, the timeline line and the audit entry.

        One helper because a status move that lands in only two of the three
        is the bug this module most needs to not have.
        """
        from app.modules.support.services.timeline import describe_status

        await self.timeline.status_change(
            ticket,
            old_status=old_status,
            new_status=new_status,
            actor_id=actor.id,
            remarks=remarks,
        )

        sentence = description or (
            f"Status changed from {describe_status(old_status)} to "
            f"{describe_status(new_status)}."
            if old_status
            else f"Status set to {describe_status(new_status)}."
        )

        await self.timeline.activity(
            ticket,
            activity_type,
            sentence,
            actor_id=actor.id,
            metadata={"old": old_status, "new": new_status, "remarks": remarks},
        )
        await self.timeline.system_message(ticket, sentence, actor_id=actor.id)
        await self.activity.record(
            ActivityAction.STATUS_CHANGE,
            entity=ticket,
            description=f"{sentence[:-1]} on ticket {ticket.ticket_no}",
            old_values={"status": old_status},
            new_values={"status": new_status},
        )

    async def _validate_category(self, category_id: uuid.UUID | None) -> None:
        """A ticket may only be filed under a live support topic.

        The taxonomy is checked as well as the category: without it, any
        category id in the system would be accepted and the support
        breakdown report would start counting blog topics.
        """
        if category_id is None:
            return

        category = await self.categories.get(category_id)
        if category is None:
            raise ValidationException(f"Category '{category_id}' does not exist.")
        if not category.is_active:
            raise BadRequestException(f"Category '{category.name}' is inactive.")

        taxonomy = category.category_type
        if taxonomy is not None and taxonomy.slug != SUPPORT_TICKET_CATEGORY_TYPE_SLUG:
            raise BadRequestException(
                f"'{category.name}' is not a support ticket category."
            )

    async def _require_known_user(self, user_id: uuid.UUID, *, role: str) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise ValidationException(f"No {role} exists with id {user_id}.")
        return user

    async def _name_of(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return "nobody"
        user = await self.users.get(user_id)
        return user.full_name if user is not None else "an unknown user"

    async def _category_name(self, category_id: uuid.UUID | None) -> str:
        if category_id is None:
            return "none"
        category = await self.categories.get(category_id)
        return category.name if category is not None else "an unknown category"
