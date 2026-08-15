"""Constants for the users module."""

import re
from enum import StrEnum

EMAIL_MAX_LENGTH = 255
PHONE_MAX_LENGTH = 20
NAME_MAX_LENGTH = 100
AVATAR_URL_MAX_LENGTH = 500
PROVIDER_USER_ID_MAX_LENGTH = 255

#: E.164 allows 15 digits at most, and no sane number has fewer than 8.
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15

_NON_PHONE_CHARACTERS = re.compile(r"[^\d+]")

#: Anything containing `@` is treated as an email; everything else as a phone.
EMAIL_MARKER = "@"


class UserStatus(StrEnum):
    """Where an account sits in its lifecycle."""

    #: Registered but not yet verified.
    PENDING = "pending"
    ACTIVE = "active"
    #: Blocked by an administrator. Cannot sign in.
    SUSPENDED = "suspended"
    #: Closed by the user. Cannot sign in.
    DEACTIVATED = "deactivated"


class AuthProvider(StrEnum):
    """How an account can authenticate."""

    PASSWORD = "password"
    GOOGLE = "google"
    FACEBOOK = "facebook"


#: Providers that arrive through an external identity flow.
SOCIAL_PROVIDERS = frozenset({AuthProvider.GOOGLE, AuthProvider.FACEBOOK})


class SocialProvider(StrEnum):
    """The social providers only, for use in a URL path.

    `AuthProvider` includes `password`, which is not something a browser can
    be redirected to. Using this in the route means `/auth/password/login`
    is a 422 from the router rather than a confusing error from inside the
    OAuth service.
    """

    GOOGLE = "google"
    FACEBOOK = "facebook"

    def as_auth_provider(self) -> AuthProvider:
        return AuthProvider(self.value)


#: The denormalized column mirroring each provider's id on `users`. The
#: `user_identities` table stays the source of truth; these columns exist so a
#: user list can filter and sort on a provider without a join.
PROVIDER_ID_COLUMNS: dict[str, str] = {
    AuthProvider.GOOGLE.value: "google_id",
    AuthProvider.FACEBOOK.value: "facebook_id",
}


class IdentifierType(StrEnum):
    """Which credential a sign-in identifier represents."""

    EMAIL = "email"
    PHONE = "phone"


def identifier_type(value: str) -> IdentifierType:
    """Classify a sign-in identifier as an email address or a phone number."""
    return IdentifierType.EMAIL if EMAIL_MARKER in value else IdentifierType.PHONE


def normalize_email(value: str) -> str:
    """Lowercase and trim, so `Ali@Example.COM` matches `ali@example.com`."""
    return value.strip().lower()


def _is_valid_length(digits: str) -> bool:
    return digits.isdigit() and MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS


def normalize_phone(value: str, *, default_country_code: str = "+880") -> str:
    """Normalize a phone number to E.164.

    Local formats are expanded using `default_country_code`, so a Bangladeshi
    user typing `01712-345678` is stored as `+8801712345678` and matches
    however they type it next time.

    Raises `ValueError` when the result cannot be a phone number.
    """
    cleaned = _NON_PHONE_CHARACTERS.sub("", value.strip())

    if not cleaned:
        raise ValueError("Phone number cannot be blank.")

    country_digits = default_country_code.lstrip("+")

    if cleaned.startswith("+"):
        normalized = cleaned
    elif cleaned.startswith("00"):
        # International prefix used across much of Europe and Asia.
        normalized = f"+{cleaned[2:]}"
    elif cleaned.startswith("0"):
        # National trunk prefix: drop it and prepend the country code.
        normalized = f"{default_country_code}{cleaned[1:]}"
    elif cleaned.startswith(country_digits) and _is_valid_length(cleaned):
        # Already carries the country code, just without the `+`. Only treated
        # that way when the length works out, so a local number that happens
        # to begin with those digits is not mangled.
        normalized = f"+{cleaned}"
    else:
        normalized = f"{default_country_code}{cleaned}"

    digits = normalized[1:]

    if not digits.isdigit():
        raise ValueError("Phone number may only contain digits after the country code.")
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise ValueError(
            f"Phone number must have between {MIN_PHONE_DIGITS} and "
            f"{MAX_PHONE_DIGITS} digits."
        )

    return normalized
