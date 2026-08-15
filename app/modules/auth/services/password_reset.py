"""Business logic for password recovery.

The governing constraint is that **this endpoint must not say who has an
account**. A password reset form is open to the internet, so if asking about
an address behaved differently from asking about a stranger's, it would be a
way to test which addresses are registered - and a list of a platform's users
is worth having. So every request is accepted the same way, whether the
account exists, is suspended, has no password yet, or has simply asked too
often.

That has a consequence worth stating: nothing here raises for an unknown
account. The refusals are logged instead, where the person asking cannot see
them.
"""

import logging
import secrets
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.core.security import hash_password, token_fingerprint
from app.modules.auth.constants import (
    PASSWORD_RESET_COOLDOWN,
    PASSWORD_RESET_MAX_PER_HOUR,
    PASSWORD_RESET_TOKEN_BYTES,
    PASSWORD_RESET_TTL,
    ResetTokenState,
    RevocationReason,
)
from app.modules.auth.delivery import ResetLinkSender, default_sender
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.repositories.password_reset import PasswordResetRepository
from app.modules.auth.repositories.refresh_token import RefreshTokenRepository
from app.modules.auth.schemas.auth import (
    ResetTokenStatus,
    SessionContext,
    TokenPair,
)
from app.modules.auth.services.auth import AuthService
from app.modules.settings.constants import SettingKey
from app.modules.settings.services.setting import SettingService
from app.modules.users.constants import (
    IdentifierType,
    UserStatus,
    identifier_type,
)
from app.modules.users.models.user import User
from app.modules.users.repositories.user import UserRepository
from app.modules.users.schemas.user import PasswordSet
from app.modules.users.services.user import UserService
from app.shared.utils.dates import truncate_to_second, utc_now

logger = logging.getLogger(__name__)

#: How much of an identifier survives masking, at each end.
MASK_VISIBLE_CHARACTERS = 2


class PasswordResetService:
    """Issues, checks and spends password reset links."""

    def __init__(
        self, session: AsyncSession, sender: ResetLinkSender | None = None
    ) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = PasswordResetRepository(session)
        self.sessions = RefreshTokenRepository(session)
        self.settings = SettingService(session)
        self.sender = sender or default_sender

    # -- Requesting -----------------------------------------------------

    async def request(
        self, identifier: str, context: SessionContext | None = None
    ) -> None:
        """Send a reset link, if there is anywhere to send one.

        Returns nothing in every case, on purpose. The caller replies with the
        same message regardless, so the shape of the response cannot be read
        as an answer to "does this account exist?".
        """
        user = await self.users.get_by_identifier(identifier)

        if user is None:
            logger.info("Password reset asked for an unknown identifier")
            return

        if not user.can_sign_in:
            # A suspended account will not be signed into anyway, so a link
            # would only be a dead end that confirms the account is real.
            logger.info(
                "Password reset refused for %s account %s", user.status, user.id
            )
            return

        if not await self._within_limits(user):
            return

        via = self._route_for(identifier)
        if not self._destination(user, via):
            logger.warning(
                "No %s on file to send a reset link for user %s", via, user.id
            )
            return

        token = await self._issue(user, via=via, context=context)
        link = await self._build_link(token)

        await self.sender.send(user, link, via=via)
        logger.info("Password reset link issued for user %s via %s", user.id, via)

    async def _within_limits(self, user: User) -> bool:
        """Throttle per account, so this cannot be used to flood an inbox."""
        latest = await self.tokens.latest_for_user(user.id)

        if (
            latest is not None
            and utc_now() - latest.created_at < PASSWORD_RESET_COOLDOWN
        ):
            logger.info("Password reset for user %s is in its cooldown", user.id)
            return False

        recent = await self.tokens.issued_since(user.id, utc_now() - timedelta(hours=1))
        if recent >= PASSWORD_RESET_MAX_PER_HOUR:
            logger.warning(
                "Password reset for user %s hit the hourly limit (%d)",
                user.id,
                recent,
            )
            return False

        return True

    async def _issue(
        self, user: User, *, via: str, context: SessionContext | None
    ) -> str:
        """Create a link, retiring any the user is already holding."""
        # Asking again must retire the older links, or an attacker who
        # triggered a reset earlier keeps a working token even after the real
        # owner has been all the way through the flow.
        await self.tokens.invalidate_outstanding(user.id)

        token = secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)

        await self.tokens.issue(
            user.id,
            token_hash=token_fingerprint(token),
            expires_at=utc_now() + PASSWORD_RESET_TTL,
            requested_via=via,
            requested_ip=context.ip_address if context else None,
        )
        await self.session.commit()

        return token

    async def _build_link(self, token: str) -> str:
        """The URL that goes in the message.

        Points at the frontend rather than at this API: the person needs a
        page to type a new password into, and where that page lives is
        configuration, not something to hardcode.
        """
        frontend = await self.settings.value(SettingKey.FRONTEND_URL.value)
        path = await self.settings.value(
            SettingKey.PASSWORD_RESET_PATH.value, "/reset-password"
        )

        if not frontend:
            # Better a bare token in the log than nothing at all, and it is
            # still enough to finish the flow through the API.
            return f"(no frontend_url configured) token={token}"

        return f"{frontend.rstrip('/')}{path or '/reset-password'}?token={token}"

    @staticmethod
    def _route_for(identifier: str) -> str:
        """Reply the way you were asked: an email request answers by email."""
        return (
            IdentifierType.EMAIL.value
            if identifier_type(identifier.strip()) is IdentifierType.EMAIL
            else IdentifierType.PHONE.value
        )

    @staticmethod
    def _destination(user: User, via: str) -> str | None:
        return user.email if via == IdentifierType.EMAIL.value else user.phone

    # -- Checking -------------------------------------------------------

    async def check(self, token: str) -> ResetTokenStatus:
        """Whether a link is still worth showing a form for.

        A page that collects a new password, submits it, and only then says
        the link expired is a poor way to find out.
        """
        stored, state = await self._resolve(token)

        if stored is None or state is not ResetTokenState.VALID:
            return ResetTokenStatus(valid=False)

        user = await self.users.get(stored.user_id)
        if user is None:
            return ResetTokenStatus(valid=False)

        return ResetTokenStatus(
            valid=True,
            masked_identifier=self._mask(
                self._destination(user, stored.requested_via or "email")
            ),
        )

    async def _resolve(
        self, token: str
    ) -> tuple[PasswordResetToken | None, ResetTokenState]:
        """Find a link and say precisely what is wrong with it, for the log."""
        stored = await self.tokens.get_by_fingerprint(token_fingerprint(token))

        if stored is None:
            return None, ResetTokenState.UNKNOWN
        if stored.is_used:
            return stored, ResetTokenState.USED
        if stored.is_invalidated:
            return stored, ResetTokenState.SUPERSEDED
        if stored.is_expired:
            return stored, ResetTokenState.EXPIRED

        return stored, ResetTokenState.VALID

    @staticmethod
    def _mask(value: str | None) -> str | None:
        """`student@bwin.example.com` -> `st••••@bwin.example.com`.

        Enough for someone to recognise their own account, not enough for a
        stranger holding the link to learn whose it is.
        """
        if not value:
            return None

        if "@" in value:
            local, _, domain = value.partition("@")
            head = local[:MASK_VISIBLE_CHARACTERS]
            return f"{head}{'•' * max(len(local) - len(head), 1)}@{domain}"

        tail = value[-MASK_VISIBLE_CHARACTERS:]
        return f"{'•' * max(len(value) - len(tail), 1)}{tail}"

    # -- Spending -------------------------------------------------------

    async def reset(self, token: str, new_password: str) -> User:
        """Set a new password and end every session on the account.

        Unlike the request step, this one does say when it fails: whoever is
        holding the link already knows an account exists, so a clear error is
        useful and gives nothing away.
        """
        stored, state = await self._resolve(token)

        if stored is None or state is not ResetTokenState.VALID:
            logger.info("Password reset rejected: token %s", state.value)
            raise BadRequestException(
                "This reset link is no longer valid. Please request a new one."
            )

        user = await self.users.get(stored.user_id)
        if user is None or not user.can_sign_in:
            raise BadRequestException(
                "This reset link is no longer valid. Please request a new one."
            )

        await self.users.update(
            user,
            password_hash=hash_password(new_password),
            # Retires the access tokens too. Revoking refresh tokens alone
            # would leave whoever prompted the reset with a working access
            # token for up to its lifetime, which is exactly the half hour
            # the reset was meant to take away from them. Truncated because
            # `iat` is whole seconds - see `AuthService._guard_not_superseded`.
            tokens_valid_from=truncate_to_second(utc_now()),
        )
        stored.spend()

        ended = await self.sessions.revoke_all_for_user(
            user.id, RevocationReason.PASSWORD_CHANGED
        )

        await self._mark_contact_verified(user, stored)
        await self.session.commit()

        logger.info("Password reset for user %s, %d sessions ended", user.id, ended)
        return user

    async def _mark_contact_verified(
        self, user: User, stored: PasswordResetToken
    ) -> None:
        """Receiving the link proves control of wherever it was sent.

        Which is exactly what verification means - so a user who registered
        and never clicked the confirmation, then reset their password, comes
        out verified rather than stuck.
        """
        now = utc_now()
        verified = False

        if (
            stored.requested_via == IdentifierType.EMAIL.value
            and not user.email_verified
        ):
            user.email_verified_at = now
            verified = True
        elif (
            stored.requested_via == IdentifierType.PHONE.value
            and not user.phone_verified
        ):
            user.phone_verified_at = now
            verified = True

        # A verified contact means the account is no longer merely pending -
        # the same rule `UserService._mark_verified` applies, so an account
        # cannot come out of a reset verified but still waiting to be.
        if verified and user.status == UserStatus.PENDING:
            user.status = UserStatus.ACTIVE.value

        await self.session.flush()

    # -- Signed-in change -----------------------------------------------

    async def change_password(
        self,
        user: User,
        *,
        current_password: str | None,
        new_password: str,
        sign_out_other_sessions: bool = True,
        context: SessionContext | None = None,
    ) -> tuple[int, TokenPair | None]:
        """Change your own password.

        Recovery is for people locked out; this is for everyone else, and it
        does not need a link because the caller has already proved who they
        are with an access token.

        Returns how many sessions ended, and a replacement token pair when the
        caller's own tokens were among them. Handing back a fresh pair is what
        lets the change invalidate *every* existing token - including the one
        making this request - without signing the caller out of the app they
        are standing in.
        """
        await UserService(self.session).set_password(
            user.id,
            PasswordSet(current_password=current_password, new_password=new_password),
        )

        if not sign_out_other_sessions:
            # Asked to leave the other sessions alone, so the old tokens stay
            # valid and there is nothing to replace.
            return 0, None

        ended = await self.sessions.revoke_all_for_user(
            user.id, RevocationReason.PASSWORD_CHANGED
        )
        await self.users.update(user, tokens_valid_from=truncate_to_second(utc_now()))
        await self.session.commit()

        replacement = await AuthService(self.session).issue_session(user, context)

        logger.info("User %s changed their password, %d sessions ended", user.id, ended)
        return ended, replacement

    # -- Maintenance ----------------------------------------------------

    async def purge_expired(self, *, older_than: timedelta | None = None) -> int:
        """Drop links old enough that they answer no useful question."""
        removed = await self.tokens.purge_expired(older_than=older_than)
        await self.session.commit()
        return removed
