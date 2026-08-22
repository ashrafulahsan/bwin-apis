"""Constants for the newsletter subscriptions module.

A subscription is one email address that has asked to hear from the platform.
There is no money involved and no plan attached: the list exists so an
administrator can send a promotion to the people who asked for one.

Two decisions shape the rest of the module.

**Confirmed opt-in.** Subscribing does not put an address on the list; it puts
it in `PENDING` and issues a link. Only following that link makes the address
`SUBSCRIBED`. Anyone can type a stranger's address into a signup box, and a
list built without confirmation is one that mails people who never asked -
which is both wrong and the fastest way to have the platform's mail marked as
spam.

**The public endpoint answers everyone identically.** It never reveals whether
an address is already on the list, for the same reason the password reset
endpoint never reveals whether an account exists: a form open to the internet
that behaves differently for known addresses is a way to test which addresses
are known.
"""

from datetime import timedelta
from enum import StrEnum

SUBSCRIPTION_EMAIL_MAX_LENGTH = 255
SUBSCRIPTION_NAME_MAX_LENGTH = 255
SUBSCRIPTION_SOURCE_MAX_LENGTH = 50
SUBSCRIPTION_REASON_MAX_LENGTH = 255

#: Long enough for IPv6, including an IPv4-mapped form. Matches the width the
#: activity log and the auth module use for the same value.
SUBSCRIPTION_IP_ADDRESS_MAX_LENGTH = 45

#: SHA-256 rendered as hex is always 64 characters. Only digests are stored -
#: a database dump gives up no working confirmation or unsubscribe links.
TOKEN_FINGERPRINT_LENGTH = 64

#: Bytes of randomness behind a token, before URL-safe encoding.
SUBSCRIPTION_TOKEN_BYTES = 32


class SubscriptionStatus(StrEnum):
    """Where an address is in its relationship with the list.

    `PENDING` asked to join and has not confirmed yet - it is *not* on the
    list and must not be mailed anything but its own confirmation link.
    `SUBSCRIBED` confirmed and should receive what is sent. `UNSUBSCRIBED`
    asked to stop, which is a request the platform is obliged to honour, so
    the row is kept rather than deleted - deleting it would let the next
    import silently put the address back. `BOUNCED` is mail that kept failing:
    kept out of every send so a dead address cannot damage the sending
    reputation that the live ones depend on.
    """

    PENDING = "pending"
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"


DEFAULT_SUBSCRIPTION_STATUS = SubscriptionStatus.PENDING

#: The statuses a campaign may actually be sent to. One name for it, so a
#: send, a count and an export cannot disagree about who is on the list.
MAILABLE_STATUSES = (SubscriptionStatus.SUBSCRIBED,)


class SubscriptionSource(StrEnum):
    """Where a signup came from, for the common cases.

    Stored as a plain string rather than an enumerated column: marketing
    invents new placements constantly, and a signup arriving from one nobody
    added here should be recorded, not rejected. These are the names the
    platform itself writes.
    """

    WEBSITE = "website"
    ADMIN = "admin"
    IMPORT = "import"


#: How long a confirmation link stays usable. Generous compared with a
#: password reset - this one is not a credential for an account, and somebody
#: who signs up on a Friday should not find a dead link on Monday.
SUBSCRIPTION_CONFIRMATION_TTL = timedelta(days=7)

#: The shortest gap between two confirmation emails to one address. Without
#: it, the public endpoint is a way to flood somebody else's inbox by
#: submitting their address over and over.
SUBSCRIPTION_CONFIRMATION_COOLDOWN = timedelta(minutes=1)

#: Returned for every subscribe request, whatever actually happened: a new
#: address, one already on the list, one still pending, or one in its
#: cooldown. Anything else would turn the endpoint into a way of testing which
#: addresses are subscribed.
SUBSCRIPTION_REQUESTED_MESSAGE = (
    "Thanks. If that address still needs confirming, a link is on its way."
)

#: Columns a free-text search looks at.
SUBSCRIPTION_SEARCH_FIELDS = ("email", "name")
