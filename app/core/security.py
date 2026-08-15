"""Password hashing, and the issuing and verification of JWTs.

Kept in `core` rather than the auth module because both layers below it need
these primitives: the auth service issues tokens, and the request dependency
verifies them.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings
from app.core.constants import TokenType
from app.shared.utils.dates import utc_now

#: bcrypt only considers the first 72 bytes of a password. Rather than let a
#: longer passphrase be silently truncated - so that two different passwords
#: could unlock the same account - anything longer is refused outright.
BCRYPT_MAX_BYTES = 72

#: Work factor. Higher is slower to brute force and slower to log in with.
BCRYPT_ROUNDS = 12


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds what bcrypt can hash safely."""

    def __init__(self) -> None:
        super().__init__(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes. "
            "Note that accented and non-Latin characters use several bytes each."
        )


def password_byte_length(password: str) -> int:
    """Length in bytes, which is what bcrypt's limit applies to."""
    return len(password.encode("utf-8"))


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    if password_byte_length(password) > BCRYPT_MAX_BYTES:
        raise PasswordTooLongError

    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password against a stored hash.

    Returns `False` rather than raising for accounts with no password - a
    social-only account should fail the check, not crash the login.
    """
    if not password_hash:
        return False

    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed or truncated hash in the database.
        return False


#: A real bcrypt hash at the project's work factor, of a value no submitted
#: password will match. Its only job is to cost the same as a genuine check.
_DUMMY_HASH = "$2b$12$t1OQJTQqCcl5HagFVD0TQuMxzpcOrw2Iykxu1hKLV0PiU7RAln1Da"


def dummy_verify(password: str) -> None:
    """Spend a bcrypt round against a throwaway hash, discarding the result.

    Signing in as an account that does not exist would otherwise skip bcrypt
    entirely and answer measurably sooner than a wrong password for an account
    that does - enough of a difference to enumerate registered addresses.
    """
    verify_password(password, _DUMMY_HASH)


# -- Tokens -------------------------------------------------------------


class TokenError(ValueError):
    """Base class for anything wrong with a presented token."""


class TokenExpiredError(TokenError):
    """The token was valid but its lifetime has passed."""

    def __init__(self) -> None:
        super().__init__("Token has expired.")


class InvalidTokenError(TokenError):
    """Signature, structure, claims or type did not check out."""

    def __init__(self, reason: str = "Token is invalid.") -> None:
        super().__init__(reason)


#: Claims every token must carry. Enforced on decode, so a token missing any
#: of them is rejected rather than silently read as `None`.
REQUIRED_CLAIMS = ("sub", "jti", "type", "iat", "exp")


@dataclass(frozen=True)
class TokenClaims:
    """The parts of a decoded token the application actually uses."""

    subject: uuid.UUID
    token_type: TokenType
    token_id: str
    issued_at: datetime
    expires_at: datetime


def _encode(
    subject: uuid.UUID, token_type: TokenType, lifetime: timedelta
) -> tuple[str, TokenClaims]:
    issued_at = utc_now()
    expires_at = issued_at + lifetime
    token_id = uuid.uuid4().hex

    payload = {
        "sub": str(subject),
        "jti": token_id,
        "type": token_type.value,
        "iat": issued_at,
        "exp": expires_at,
    }

    token = jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return token, TokenClaims(
        subject=subject,
        token_type=token_type,
        token_id=token_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def create_access_token(subject: uuid.UUID) -> tuple[str, TokenClaims]:
    """Short-lived token proving who the caller is.

    Deliberately carries no roles or permissions. Reading them from the
    database on each request costs one indexed query and means a revoked role
    stops working immediately, rather than lingering until the token expires.
    """
    return _encode(
        subject,
        TokenType.ACCESS,
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(subject: uuid.UUID) -> tuple[str, TokenClaims]:
    """Long-lived token whose only power is to mint a new access token."""
    return _encode(
        subject,
        TokenType.REFRESH,
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: TokenType | None = None) -> TokenClaims:
    """Verify a token's signature and claims, returning what it asserts.

    Raises `TokenExpiredError` or `InvalidTokenError`; never returns a partly
    trusted result.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            # A list of one: passing the configured algorithm explicitly is
            # what stops a token declaring `alg: none` from being accepted.
            algorithms=[settings.jwt_algorithm],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError from exc

    try:
        token_type = TokenType(payload["type"])
    except ValueError as exc:
        raise InvalidTokenError("Unknown token type.") from exc

    # A refresh token must not be usable as an access token, or a stolen one
    # would grant API access directly instead of only a new session.
    if expected_type is not None and token_type is not expected_type:
        raise InvalidTokenError(f"Expected a {expected_type.value} token.")

    try:
        subject = uuid.UUID(payload["sub"])
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidTokenError("Token subject is not a user id.") from exc

    return TokenClaims(
        subject=subject,
        token_type=token_type,
        token_id=str(payload["jti"]),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )


def token_fingerprint(token: str) -> str:
    """SHA-256 of a token, which is what gets stored rather than the token.

    Refresh tokens are bearer credentials: anyone holding one can keep a
    session alive. Storing only the digest means a leaked database dump hands
    over no usable sessions. SHA-256 rather than bcrypt because the input is
    already high entropy, and every refresh has to look the row up by it.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
