"""How an inquiry notification reaches the desk, and the visitor.

There is no mail transport in the platform yet - that arrives with the
notifications module. Rather than block the contact form on it, or bolt a
half-built mailer onto this commit, delivery sits behind one small interface
with a logging implementation, exactly as password recovery already does in
`app.modules.auth.delivery` and newsletter confirmation in
`app.modules.subscriptions.delivery`. Swapping in a real sender later means
providing another `InquiryNotifier`, and nothing in the service changes.

Two messages go out per submission and they are not the same kind of thing.
The **notification** tells the desk that somebody asked something, and carries
the visitor's details because that is its entire purpose. The
**acknowledgement** goes back to the visitor and deliberately carries nothing
but confirmation: the address is unverified at that point, so anything echoed
into it is content sent to whoever actually owns the mailbox.
"""

import logging
from typing import Protocol

from app.core.config import settings
from app.modules.inquiries.models.contact_inquiry import ContactInquiry

logger = logging.getLogger(__name__)


class InquiryNotifier(Protocol):
    """Sends the two messages a submitted inquiry generates."""

    async def notify_desk(self, inquiry: ContactInquiry, recipient: str) -> None:
        """Tell `recipient` that `inquiry` came in."""
        ...

    async def acknowledge_submitter(self, inquiry: ContactInquiry) -> None:
        """Confirm receipt to whoever submitted `inquiry`."""
        ...


class LoggingInquiryNotifier:
    """Writes the messages to the log instead of sending them.

    The default until the notifications module lands. Neither method raises:
    a delivery failure must not roll back an inquiry that was otherwise
    accepted, or the visitor would see an error and submit again - producing
    a duplicate for somebody to chase twice, and tripping the rate limit for
    something that was not their fault.
    """

    async def notify_desk(self, inquiry: ContactInquiry, recipient: str) -> None:
        if settings.is_production:
            # Production logs are widely readable and this line would
            # otherwise put a member of the public's phone number in them.
            logger.info("Contact inquiry notification sent")
            return

        logger.warning(
            "No mail transport configured. Contact inquiry notification for "
            "%s:\n  from: %s <%s> %s\n  interested in: %s\n  message: %s",
            recipient,
            inquiry.full_name,
            inquiry.email,
            inquiry.phone,
            inquiry.interested_in,
            inquiry.message or "(none)",
        )

    async def acknowledge_submitter(self, inquiry: ContactInquiry) -> None:
        if settings.is_production:
            logger.info("Contact inquiry acknowledgement sent")
            return

        logger.warning(
            "No mail transport configured. Contact inquiry acknowledgement for %s",
            inquiry.email,
        )


#: The notifier the service uses unless one is passed in.
default_notifier: InquiryNotifier = LoggingInquiryNotifier()


async def deliver_inquiry_messages(
    inquiry: ContactInquiry,
    *,
    notifier: InquiryNotifier,
    recipient: str | None,
    acknowledge: bool,
) -> None:
    """Send whichever messages are configured, swallowing failures.

    Written as one function so the router can hand exactly this to
    `BackgroundTasks`: it runs after the response has gone out, which is
    where anything the visitor should not be made to wait for belongs.

    Errors are logged and dropped. By the time this runs the inquiry is
    committed and the caller has already been told it was received, so
    raising here could only produce a traceback nobody is waiting for.
    """
    try:
        if recipient:
            await notifier.notify_desk(inquiry, recipient)
        else:
            logger.info(
                "No contact inquiry notification address is configured; "
                "skipping the desk notification."
            )

        if acknowledge:
            await notifier.acknowledge_submitter(inquiry)
    except Exception:
        logger.exception(
            "Could not deliver the notifications for contact inquiry %s",
            inquiry.id,
        )
