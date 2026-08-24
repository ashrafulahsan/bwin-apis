"""Constants and vocabulary for website contact inquiries."""

from enum import StrEnum

INQUIRY_NAME_MAX_LENGTH = 255
INQUIRY_EMAIL_MAX_LENGTH = 255
INQUIRY_PHONE_MAX_LENGTH = 50
INQUIRY_INTEREST_MAX_LENGTH = 100
INQUIRY_STATUS_MAX_LENGTH = 50
INQUIRY_IP_MAX_LENGTH = 100

#: How much of a submitted user agent is kept. Browsers send long strings and
#: the tail carries nothing an operator reads; the column is TEXT, so this is
#: about not storing junk rather than about fitting.
INQUIRY_USER_AGENT_MAX_LENGTH = 512


class InterestedIn(StrEnum):
    """What the visitor says they are here about.

    These are the options on the public form. Stored as text rather than a
    database enum so adding one is a deploy rather than a migration, and
    validated against this list on the way in - a free-text column that
    accepts anything makes the "interested in" report meaningless.
    """

    SKILL_DEVELOPMENT = "skill_development"
    CONSULTANCY = "consultancy"
    BUSINESS_AUTOMATION = "business_automation"
    NOT_SURE_YET = "not_sure_yet"


#: Labels for the public form and for exports, so the wording lives with the
#: values instead of being reinvented per client.
INTEREST_LABELS: dict[InterestedIn, str] = {
    InterestedIn.SKILL_DEVELOPMENT: "Skill Development",
    InterestedIn.CONSULTANCY: "Consultancy",
    InterestedIn.BUSINESS_AUTOMATION: "Business Automation",
    InterestedIn.NOT_SURE_YET: "Not Sure Yet",
}


class InquiryStatus(StrEnum):
    """Where an inquiry has got to in the sales conversation."""

    NEW = "new"
    CONTACTED = "contacted"
    IN_PROGRESS = "in_progress"
    CONVERTED = "converted"
    CLOSED = "closed"
    SPAM = "spam"


#: Statuses that mean nobody is working the inquiry any more. Used by the
#: dashboard counts and by the default "open work" filter.
CLOSED_STATUSES: frozenset[InquiryStatus] = frozenset(
    {InquiryStatus.CONVERTED, InquiryStatus.CLOSED, InquiryStatus.SPAM}
)

INQUIRY_SEARCH_FIELDS = ("full_name", "email", "phone")


#: The one sentence the public endpoint ever returns.
#:
#: Fixed regardless of what happened - accepted, duplicate, throttled - for
#: the same reason the newsletter signup has a fixed reply: a form open to the
#: internet that answered differently for known addresses would be a way to
#: test which addresses are already in the database.
INQUIRY_SUBMITTED_MESSAGE = "Inquiry submitted successfully"


class InquirySettingKey(StrEnum):
    """Settings this module reads, seeded by its migration."""

    #: Submissions allowed from one address within the window below.
    RATE_LIMIT_MAX = "contact_inquiry_rate_limit_max"
    #: Length of the rate limit window, in minutes.
    RATE_LIMIT_WINDOW_MINUTES = "contact_inquiry_rate_limit_window_minutes"
    #: Where the "new inquiry" notification goes. Blank disables it.
    NOTIFY_EMAIL = "contact_inquiry_notify_email"
    #: Whether the submitter gets an acknowledgement.
    ACKNOWLEDGE_SUBMITTER = "contact_inquiry_acknowledge_submitter"


#: Five submissions from one address in fifteen minutes is generous for a
#: person and stingy for a script. Both halves are settings, because the right
#: numbers depend on how much traffic the site actually gets.
DEFAULT_RATE_LIMIT_MAX = 5
DEFAULT_RATE_LIMIT_WINDOW_MINUTES = 15

#: Told to a caller who trips the limit. Deliberately vague about the numbers:
#: publishing the exact window is publishing how to pace a script under it.
INQUIRY_RATE_LIMITED_MESSAGE = (
    "Too many inquiries have been submitted from this connection. "
    "Please try again shortly."
)
