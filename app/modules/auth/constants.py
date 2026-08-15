"""Constants for the authentication module."""

from datetime import timedelta
from enum import StrEnum

#: SHA-256 rendered as hex is always 64 characters.
TOKEN_FINGERPRINT_LENGTH = 64

USER_AGENT_MAX_LENGTH = 255
#: Long enough for IPv6, including an IPv4-mapped form.
IP_ADDRESS_MAX_LENGTH = 45

#: The scheme clients send tokens with: `Authorization: Bearer <token>`.
BEARER_SCHEME = "Bearer"

#: Returned for every failed sign-in, whatever actually went wrong. Saying
#: which half was wrong would confirm that an address is registered.
INVALID_CREDENTIALS_MESSAGE = "Incorrect credentials. Please check and try again."


# -- Password recovery --------------------------------------------------

#: Returned for every password reset request, whether or not the account
#: exists, is suspended, or was throttled. Anything else would turn the
#: endpoint into a way of testing which addresses are registered.
RESET_REQUESTED_MESSAGE = (
    "If that account exists, a link to reset the password is on its way."
)

#: How long a reset link stays usable. Short, because it is a credential
#: sitting in an inbox: long enough to notice the email and act on it, not
#: long enough to still work weeks later when the mailbox is resold or
#: restored from a backup.
PASSWORD_RESET_TTL = timedelta(hours=1)

#: Bytes of randomness behind a reset token, before URL-safe encoding. The
#: token is the only thing standing between a stranger and an account, and it
#: has to survive being guessed at.
PASSWORD_RESET_TOKEN_BYTES = 32

#: The shortest gap between two reset emails for one account. Without it, the
#: endpoint is a way to flood somebody else's inbox.
PASSWORD_RESET_COOLDOWN = timedelta(minutes=1)

#: How many links one account may be sent per hour, however they are spaced.
PASSWORD_RESET_MAX_PER_HOUR = 5


class ResetTokenState(StrEnum):
    """Why a reset token is not usable.

    Kept apart from the message shown to the user, which stays vague on
    purpose; this is what gets logged.
    """

    VALID = "valid"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    USED = "used"
    SUPERSEDED = "superseded"


class RevocationReason(StrEnum):
    """Why a refresh token stopped being usable.

    Recorded rather than inferred, so an audit can tell an ordinary sign-out
    from a session cut short by a suspected stolen token.
    """

    #: The user signed out of this session.
    LOGOUT = "logout"
    #: The user signed out everywhere.
    LOGOUT_ALL = "logout_all"
    #: Replaced by a newer token during a refresh.
    ROTATED = "rotated"
    #: An already-used token was presented again - see `AuthService.refresh`.
    REUSE_DETECTED = "reuse_detected"
    #: The account was suspended, deactivated or deleted.
    ACCOUNT_CLOSED = "account_closed"
    #: The password changed, so older sessions should not survive.
    PASSWORD_CHANGED = "password_changed"
