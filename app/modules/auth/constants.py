"""Constants for the authentication module."""

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
