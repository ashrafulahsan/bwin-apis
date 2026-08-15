"""Password hashing and verification.

Token issuing and verification land here too, with the authentication module.
"""

import bcrypt

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
