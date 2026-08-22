"""The unsubscribe token, and why it is derived rather than stored.

Every message sent to the list carries an unsubscribe link, so whatever is
composing that message needs the token at send time - potentially years after
the person signed up. A random token hashed into the row cannot supply that:
the digest is all that survives, and a digest cannot be turned back into a
link. Storing the token in the clear instead would mean a leaked table is a
list of working unsubscribe links for every subscriber.

So the token is not stored at all. It is an HMAC of the subscription's id
under the application secret, which makes it deterministic - the sender can
recompute it whenever it needs one - and unguessable without the secret. The
row holds nothing to leak, and verification is a recomputation rather than a
lookup.

Two consequences worth knowing. Rotating `secret_key` invalidates every
outstanding unsubscribe link, exactly as it invalidates every issued JWT.
And the token identifies the subscription it belongs to, so `parse` returns
that id and the caller loads the row itself.
"""

import hashlib
import hmac
import uuid

from app.core.config import settings

#: Separates the id from its signature inside one opaque token string.
_SEPARATOR = "."

#: Domain separation. Without it, a signature minted here would be valid
#: anywhere else the same secret signs a bare UUID.
_PURPOSE = "newsletter-unsubscribe"


def _signature(subscription_id: uuid.UUID) -> str:
    return hmac.new(
        settings.secret_key.get_secret_value().encode("utf-8"),
        f"{_PURPOSE}:{subscription_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def build_unsubscribe_token(subscription_id: uuid.UUID) -> str:
    """The token for one subscription's unsubscribe link.

    Safe to put in a URL: it is a UUID and a hex digest joined by a dot.
    """
    return f"{subscription_id}{_SEPARATOR}{_signature(subscription_id)}"


def parse_unsubscribe_token(token: str) -> uuid.UUID | None:
    """The subscription a token belongs to, or `None` if it is not genuine.

    Returns `None` for anything malformed rather than raising: this parses
    whatever arrives in a query string, and a truncated link is a bad request,
    not an exception.
    """
    raw_id, separator, signature = token.strip().partition(_SEPARATOR)
    if not separator or not signature:
        return None

    try:
        subscription_id = uuid.UUID(raw_id)
    except ValueError:
        return None

    # Constant time: a plain `==` leaks how much of a forged signature was
    # right, which is enough to build the rest of it one character at a time.
    if not hmac.compare_digest(signature, _signature(subscription_id)):
        return None

    return subscription_id
