"""Who may see and do what to a given ticket.

Permissions say what a role may do at all; this module says which tickets
those verbs reach. It is deliberately a small set of pure predicates over
`(user, ticket)` rather than checks scattered through the service: the rule
"a student sees only their own tickets" has to hold identically on the read,
the reply, the close and the export, and the only way to be sure of that is
to write it once.

Nothing here touches the database, so the whole policy is testable without
one.
"""

from enum import StrEnum

from app.modules.support.constants import TicketStatus
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.permissions import SupportPermission
from app.modules.users.models.user import User


class TicketScope(StrEnum):
    """Which slice of the queue a caller can reach."""

    #: Only tickets they raised.
    OWN = "own"
    #: Only tickets assigned to them, plus any they raised themselves.
    ASSIGNED = "assigned"
    #: Everything.
    ALL = "all"


def scope_for(user: User) -> TicketScope:
    """The widest slice this caller is entitled to.

    Driven by permissions rather than role slugs, so reorganising roles does
    not silently widen anyone's view. `ticket.view_all` is the one that opens
    the whole queue; `ticket.assign` implies it, because an administrator who
    can hand a ticket to someone must be able to see it first.
    """
    held = user.permission_codes

    if SupportPermission.VIEW_ALL in held or SupportPermission.ASSIGN in held:
        return TicketScope.ALL

    # A trainer is recognised by being able to move a ticket through the
    # workflow, which a student cannot do.
    if SupportPermission.STATUS in held or SupportPermission.ESCALATE in held:
        return TicketScope.ASSIGNED

    return TicketScope.OWN


def is_owner(user: User, ticket: SupportTicket) -> bool:
    return ticket.student_id == user.id


def is_assignee(user: User, ticket: SupportTicket) -> bool:
    return ticket.assigned_to == user.id


def is_staff(user: User) -> bool:
    """Anyone whose scope reaches past their own tickets."""
    return scope_for(user) is not TicketScope.OWN


def can_view_ticket(user: User, ticket: SupportTicket) -> bool:
    """Whether this caller may open this ticket at all."""
    scope = scope_for(user)

    if scope is TicketScope.ALL:
        return True
    if scope is TicketScope.ASSIGNED:
        return is_assignee(user, ticket) or is_owner(user, ticket)

    return is_owner(user, ticket)


def can_see_internal_notes(user: User) -> bool:
    """Internal notes are staff-only, and never shown to the student.

    Gated on holding the permission rather than on being staff: a trainer who
    may reply is not automatically entitled to read what administrators said
    about the ticket between themselves.
    """
    return SupportPermission.INTERNAL_NOTE in user.permission_codes


def can_reply_to(user: User, ticket: SupportTicket) -> bool:
    """Whether this caller may add a message to this ticket."""
    if SupportPermission.REPLY not in user.permission_codes:
        return False

    return can_view_ticket(user, ticket)


def can_close(user: User, ticket: SupportTicket) -> bool:
    """Closing is open to the student, the assigned agent, and admins.

    A trainer who is not the assignee has no business closing someone else's
    ticket, which is why holding `ticket.status` alone is not enough here.
    """
    if not can_view_ticket(user, ticket):
        return False

    if is_owner(user, ticket) or is_assignee(user, ticket):
        return True

    return scope_for(user) is TicketScope.ALL


def can_reopen(user: User, ticket: SupportTicket) -> bool:
    """Reopening is allowed to the same people who may close.

    Whether the reopen *window* has expired is a separate question, answered
    by the service - it needs the settings table, and this module stays pure.
    """
    return can_close(user, ticket)


def can_submit_feedback(user: User, ticket: SupportTicket) -> bool:
    """Only the student who raised it, and only once it is finished."""
    if not is_owner(user, ticket):
        return False

    return TicketStatus(ticket.status) in {TicketStatus.RESOLVED, TicketStatus.CLOSED}


def can_download_attachment(user: User, ticket: SupportTicket) -> bool:
    """A file is exactly as readable as the ticket it hangs off.

    Attachments are served through the API rather than from a public
    directory precisely so this check happens on every fetch.
    """
    return can_view_ticket(user, ticket)
