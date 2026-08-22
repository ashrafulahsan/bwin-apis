"""How a confirmation link reaches the address that asked for it.

There is no mail transport in the platform yet - that arrives with the
notifications module. Rather than block the subscription flow on it, or bolt a
half-built mailer onto this commit, delivery sits behind one small interface
with a logging implementation, exactly as password recovery already does in
`app.modules.auth.delivery`. Swapping in a real sender later is a matter of
providing another `ConfirmationLinkSender`, and nothing in the service
changes.

The logging sender writes the whole link to the application log outside
production, which is how a developer completes the flow without a mailbox. In
production it deliberately logs only *that* a link was sent: the link is the
token, and a readable log should not be a way onto somebody else's
subscription.
"""

import logging
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class ConfirmationLinkSender(Protocol):
    """Delivers a confirmation link to an address that asked to subscribe."""

    async def send(self, email: str, link: str) -> None:
        """Send `link` to `email`."""
        ...


class LoggingConfirmationLinkSender:
    """Writes the link to the log instead of sending it.

    The default until the notifications module lands. It never raises: a
    delivery failure must not roll back a signup that was otherwise accepted,
    or the visitor would see an error and submit again, tripping the cooldown
    for something that was not their fault.
    """

    async def send(self, email: str, link: str) -> None:
        if settings.is_production:
            # Production logs are widely readable; the link is a credential.
            logger.info("Newsletter confirmation link sent")
            return

        logger.warning(
            "No mail transport configured. Newsletter confirmation link "
            "for %s:\n  %s",
            email,
            link,
        )


#: The sender the service uses unless one is passed in.
default_sender: ConfirmationLinkSender = LoggingConfirmationLinkSender()
