"""The `state` parameter, and the cookie that binds it to one browser.

`state` exists to stop login CSRF: without it, an attacker can complete a
sign-in with *their* provider account in *your* browser, quietly leaving you
signed in as them. Signing the value proves the server issued it, but a signed
value alone is not enough - an attacker can simply start a sign-in and collect
one. So the state carries only the *digest* of a nonce, and the nonce itself
goes to the browser in an HttpOnly cookie. Completing the flow needs both
halves, which only the browser that started it has.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

import jwt

from app.core.config import settings
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)

#: Name of the cookie holding the nonce, per provider.
STATE_COOKIE_PREFIX = "bwin_oauth_state"

#: A sign-in that takes longer than this has been abandoned. Short, because
#: the window is only as long as it takes a person to type a password.
STATE_TTL = timedelta(minutes=10)

#: Marks the token's purpose, so a state cannot be presented as an access
#: token or the other way round.
STATE_TOKEN_TYPE = "oauth_state"


class InvalidStateError(ValueError):
    """The state was missing, expired, forged, or from another browser."""


@dataclass(frozen=True)
class OAuthState:
    """What the state token asserts."""

    provider: str
    #: Where to send the browser once the sign-in finishes. Validated against
    #: the configured frontend before use, never trusted as given.
    redirect_to: str | None


def cookie_name(provider: str) -> str:
    """One cookie per provider, so two sign-ins cannot clobber each other."""
    return f"{STATE_COOKIE_PREFIX}_{provider}"


def new_nonce() -> str:
    """A fresh secret for one sign-in attempt."""
    return secrets.token_urlsafe(32)


def _digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def issue(provider: str, nonce: str, redirect_to: str | None = None) -> str:
    """Build the signed `state` value to hand the provider."""
    issued_at = utc_now()

    return jwt.encode(
        {
            "type": STATE_TOKEN_TYPE,
            "provider": provider,
            # The nonce never leaves this server in the clear; only its
            # digest travels through the provider.
            "nonce_hash": _digest(nonce),
            "redirect_to": redirect_to,
            "iat": issued_at,
            "exp": issued_at + STATE_TTL,
        },
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def verify(state: str, provider: str, nonce: str | None) -> OAuthState:
    """Check a returned state against the cookie that should accompany it.

    Raises `InvalidStateError` on anything unexpected.
    """
    if not state:
        raise InvalidStateError("The sign-in is missing its state value.")

    if not nonce:
        # No cookie means this browser never started the sign-in - either the
        # attack this guard exists for, or third-party cookies being blocked.
        raise InvalidStateError(
            "This sign-in did not start in this browser. Please try again."
        )

    try:
        payload = jwt.decode(
            state,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["type", "provider", "nonce_hash", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidStateError(
            "This sign-in took too long. Please try again."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidStateError("This sign-in could not be verified.") from exc

    if payload.get("type") != STATE_TOKEN_TYPE:
        raise InvalidStateError("This sign-in could not be verified.")

    if payload.get("provider") != provider:
        # A state issued for Google must not complete a Facebook sign-in.
        raise InvalidStateError("This sign-in was started with another provider.")

    # `compare_digest` because this is a secret-derived comparison; the
    # timing of a mismatch should not say how much of it matched.
    if not secrets.compare_digest(str(payload["nonce_hash"]), _digest(nonce)):
        logger.warning("OAuth state nonce mismatch for %s", provider)
        raise InvalidStateError(
            "This sign-in did not start in this browser. Please try again."
        )

    redirect_to = payload.get("redirect_to")

    return OAuthState(
        provider=provider,
        redirect_to=str(redirect_to) if redirect_to else None,
    )
