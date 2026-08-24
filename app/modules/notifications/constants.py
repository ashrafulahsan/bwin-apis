"""Constants and vocabulary for notifications."""

from enum import StrEnum

NOTIFICATION_TITLE_MAX_LENGTH = 255
NOTIFICATION_ICON_MAX_LENGTH = 255
NOTIFICATION_IMAGE_URL_MAX_LENGTH = 500


class NotificationType(StrEnum):
    """Who wrote it.

    The distinction matters for more than reporting: an administrator may
    edit and withdraw their own announcements, while a system notification
    records something that actually happened - "your certificate is ready" -
    and editing one after the fact would make it a lie.
    """

    ADMIN = "admin"
    SYSTEM = "system"


class DeliveryType(StrEnum):
    """How the audience is chosen.

    Each value names a resolution strategy; `target_ids` is read against
    whichever one is chosen, and ignored by `GLOBAL`, which has no targets.
    """

    GLOBAL = "global"
    ROLE = "role"
    COURSE = "course"
    USER = "user"


#: The delivery types that need `target_ids`. `global` is the only one that
#: does not, and passing targets with it is a mistake worth refusing rather
#: than silently ignoring.
TARGETED_DELIVERY_TYPES: frozenset[DeliveryType] = frozenset(
    {DeliveryType.ROLE, DeliveryType.COURSE, DeliveryType.USER}
)


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


NOTIFICATION_SEARCH_FIELDS = ("title", "short_message")


#: System notifications the platform raises for itself. Naming them here
#: rather than passing free text from each caller is what keeps the same
#: event worded the same way wherever it is raised from, and makes "how many
#: certificate notices went out" answerable.
class SystemEvent(StrEnum):
    # -- Authentication -------------------------------------------------
    ACCOUNT_CREATED = "account_created"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFIED = "email_verified"

    # -- Learning --------------------------------------------------------
    COURSE_ENROLLED = "course_enrolled"
    COURSE_COMPLETED = "course_completed"
    CERTIFICATE_GENERATED = "certificate_generated"
    ASSIGNMENT_SUBMITTED = "assignment_submitted"
    ASSIGNMENT_GRADED = "assignment_graded"
    LIVE_CLASS_REMINDER = "live_class_reminder"

    # -- Content ----------------------------------------------------------
    BLOG_PUBLISHED = "blog_published"
    EVENT_PUBLISHED = "event_published"

    # -- Support -----------------------------------------------------------
    TICKET_REPLIED = "ticket_replied"
    TICKET_RESOLVED = "ticket_resolved"


#: Default wording and priority per event, so a caller supplies only what is
#: specific to the occasion. Every field is overridable at the call site.
SYSTEM_EVENT_TEMPLATES: dict[SystemEvent, dict[str, str]] = {
    SystemEvent.ACCOUNT_CREATED: {
        "title": "Welcome aboard",
        "short_message": "Your account is ready to use.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.PASSWORD_RESET: {
        "title": "Your password was changed",
        "short_message": "If this was not you, contact support immediately.",
        "priority": NotificationPriority.HIGH,
    },
    SystemEvent.EMAIL_VERIFIED: {
        "title": "Email address verified",
        "short_message": "Your email address has been confirmed.",
        "priority": NotificationPriority.LOW,
    },
    SystemEvent.COURSE_ENROLLED: {
        "title": "You are enrolled",
        "short_message": "Your course is ready to start.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.COURSE_COMPLETED: {
        "title": "Course completed",
        "short_message": "Congratulations on finishing your course.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.CERTIFICATE_GENERATED: {
        "title": "Your certificate is ready",
        "short_message": "Download your certificate from your dashboard.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.ASSIGNMENT_SUBMITTED: {
        "title": "Assignment received",
        "short_message": "Your submission has been recorded.",
        "priority": NotificationPriority.LOW,
    },
    SystemEvent.ASSIGNMENT_GRADED: {
        "title": "Assignment graded",
        "short_message": "Your assignment has been marked.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.LIVE_CLASS_REMINDER: {
        "title": "Live class starting soon",
        "short_message": "Your session begins shortly.",
        "priority": NotificationPriority.HIGH,
    },
    SystemEvent.BLOG_PUBLISHED: {
        "title": "New article published",
        "short_message": "There is something new to read.",
        "priority": NotificationPriority.LOW,
    },
    SystemEvent.EVENT_PUBLISHED: {
        "title": "New event announced",
        "short_message": "A new event has been published.",
        "priority": NotificationPriority.LOW,
    },
    SystemEvent.TICKET_REPLIED: {
        "title": "Your support ticket has a reply",
        "short_message": "Someone has responded to your ticket.",
        "priority": NotificationPriority.NORMAL,
    },
    SystemEvent.TICKET_RESOLVED: {
        "title": "Your support ticket was resolved",
        "short_message": "Let us know if the problem comes back.",
        "priority": NotificationPriority.NORMAL,
    },
}
