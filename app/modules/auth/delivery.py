"""How a password reset link reaches the person who asked for it.

There is no mail or SMS transport in the platform yet - that arrives with the
notifications module. Rather than block password recovery on it, or bolt a
half-built mailer onto this commit, delivery sits behind one small interface
with a logging implementation. Swapping in a real sender later is a matter of
providing another `ResetLinkSender`, and nothing in the service changes.

The logging sender writes the whole link to the application log outside
production, which is how a developer completes the flow without a mailbox. In
production it deliberately logs only *that* a link was sent: an access to the
log file would otherwise be an access to every account.
"""

import logging
from typing import Protocol

from app.core.config import settings
from app.modules.users.models.user import User

logger = logging.getLogger(__name__)


class ResetLinkSender(Protocol):
    """Delivers a reset link to a user."""

    async def send(self, user: User, link: str, *, via: str) -> None:
        """Send `link` to `user`. `via` is `email` or `phone`."""
        ...


class LoggingResetLinkSender:
    """Writes the link to the log instead of sending it.

    The default until the notifications module lands. It never raises: a
    delivery failure must not roll back a reset request that was otherwise
    accepted, or the user would see an error and try again, tripping the
    throttle for something that was not their fault.
    """

    async def send(self, user: User, link: str, *, via: str) -> None:
        destination = user.email if via == "email" else user.phone

        if settings.is_production:
            # Production logs are widely readable; the link is a credential.
            logger.info("Password reset link sent to user %s via %s", user.id, via)
            return

        logger.warning(
            "No mail transport configured. Password reset link for %s (%s):\n  %s",
            destination,
            user.id,
            link,
        )


#: The sender the service uses unless one is passed in.
default_sender: ResetLinkSender = LoggingResetLinkSender()
