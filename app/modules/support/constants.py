"""Constants, vocabulary and lifecycle rules for support tickets.

The status machine lives here rather than in the service, because the same
transitions have to be understood in three places - the service that applies
them, the schema that documents them, and the tests that pin them down. One
table beats three copies that can drift.
"""

from enum import StrEnum

TICKET_NO_MAX_LENGTH = 30
TICKET_SUBJECT_MAX_LENGTH = 255
TICKET_REASON_MAX_LENGTH = 500
TICKET_REMARKS_MAX_LENGTH = 500

ATTACHMENT_FILE_NAME_MAX_LENGTH = 255
ATTACHMENT_PATH_MAX_LENGTH = 500
ATTACHMENT_MIME_TYPE_MAX_LENGTH = 150

ACTIVITY_TYPE_MAX_LENGTH = 50
ACTIVITY_DESCRIPTION_MAX_LENGTH = 500

#: Serial format. The year is part of the number so a reader can date a
#: ticket from the reference alone, and the counter restarts each January.
TICKET_NO_PREFIX = "TKT"
TICKET_NO_SEQUENCE_DIGITS = 6

#: Slug of the taxonomy support ticket categories are filed under.
SUPPORT_TICKET_CATEGORY_TYPE_SLUG = "support_ticket"

FEEDBACK_MIN_RATING = 1
FEEDBACK_MAX_RATING = 5


class TicketStatus(StrEnum):
    """Where a ticket sits in its lifecycle."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_STUDENT = "waiting_for_student"
    WAITING_FOR_TRAINER = "waiting_for_trainer"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketSource(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    ADMIN = "admin"


class TicketActivityType(StrEnum):
    """What a timeline entry records.

    Distinct from `ActivityAction` in the platform-wide audit log: that trail
    answers "what did this account do", this one answers "what happened to
    this ticket" and is shown to the student.
    """

    CREATED = "ticket_created"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    CATEGORY_CHANGED = "category_changed"
    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    REPLY_ADDED = "reply_added"
    INTERNAL_NOTE_ADDED = "internal_note_added"
    ATTACHMENT_UPLOADED = "attachment_uploaded"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"
    MERGED = "merged"
    FEEDBACK_SUBMITTED = "feedback_submitted"


#: Statuses that mean the conversation is over. Replying to one of these
#: reopens it rather than being silently appended to a finished thread.
TERMINAL_STATUSES: frozenset[TicketStatus] = frozenset(
    {TicketStatus.RESOLVED, TicketStatus.CLOSED}
)

#: Statuses a ticket may still be worked from. The complement of the above,
#: named so call sites read as intent rather than as a negation.
ACTIVE_STATUSES: frozenset[TicketStatus] = frozenset(TicketStatus) - TERMINAL_STATUSES

#: Which statuses each status may move to.
#:
#: A ticket is never dragged backwards into `open` - `reopened` exists so the
#: distinction between "never touched" and "came back" survives in reporting.
#: `closed` is a near-dead end: only a reopen leaves it, and only inside the
#: window the settings table defines.
STATUS_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_FOR_STUDENT,
            TicketStatus.WAITING_FOR_TRAINER,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.IN_PROGRESS: frozenset(
        {
            TicketStatus.WAITING_FOR_STUDENT,
            TicketStatus.WAITING_FOR_TRAINER,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.WAITING_FOR_STUDENT: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_FOR_TRAINER,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.WAITING_FOR_TRAINER: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_FOR_STUDENT,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.ESCALATED: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_FOR_STUDENT,
            TicketStatus.WAITING_FOR_TRAINER,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.RESOLVED: frozenset({TicketStatus.CLOSED, TicketStatus.REOPENED}),
    TicketStatus.CLOSED: frozenset({TicketStatus.REOPENED}),
    TicketStatus.REOPENED: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_FOR_STUDENT,
            TicketStatus.WAITING_FOR_TRAINER,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }
    ),
}


def can_transition(current: TicketStatus | str, target: TicketStatus | str) -> bool:
    """Whether `current -> target` is a move the lifecycle allows.

    Re-stating the current status is allowed and is a no-op, which keeps an
    idempotent retry from failing.
    """
    current_status = TicketStatus(current)
    target_status = TicketStatus(target)

    if current_status is target_status:
        return True

    return target_status in STATUS_TRANSITIONS[current_status]


TICKET_SEARCH_FIELDS = ("ticket_no", "subject", "description")

TICKET_SORTABLE_FIELDS = frozenset(
    {
        "created_at",
        "updated_at",
        "ticket_no",
        "subject",
        "status",
        "priority",
        "last_reply_at",
        "resolved_at",
        "closed_at",
    }
)


class SupportSettingKey(StrEnum):
    """Settings this module reads, seeded by its migration."""

    #: Days after closing during which a student may still reopen a ticket.
    REOPEN_WINDOW_DAYS = "support_ticket_reopen_days"
    #: Upload ceiling for one attachment, in megabytes.
    MAX_UPLOAD_MB = "support_ticket_max_upload_mb"
    #: Comma separated extensions an attachment may use.
    ALLOWED_EXTENSIONS = "support_ticket_allowed_extensions"
    #: How many attachments one ticket may accumulate.
    MAX_ATTACHMENTS_PER_TICKET = "support_ticket_max_attachments"


DEFAULT_REOPEN_WINDOW_DAYS = 7
DEFAULT_MAX_UPLOAD_MB = 10
DEFAULT_MAX_ATTACHMENTS_PER_TICKET = 20
DEFAULT_ALLOWED_EXTENSIONS = (
    ".jpg,.jpeg,.png,.webp,.gif,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.log"
)

#: Where attachments are written, under the configured upload directory.
ATTACHMENT_SUBDIRECTORY = "support_tickets"
