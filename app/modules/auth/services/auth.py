"""Business logic for authentication: signing in, refreshing and signing out."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import TokenType
from app.core.context import get_request_context
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import (
    TokenClaims,
    TokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify,
    token_fingerprint,
    verify_password,
)
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.auth.constants import (
    INVALID_CREDENTIALS_MESSAGE,
    RevocationReason,
)
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.auth.repositories.refresh_token import RefreshTokenRepository
from app.modules.auth.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    SessionContext,
    TokenPair,
)
from app.modules.users.constants import AuthProvider
from app.modules.users.models.user import User
from app.modules.users.repositories.user import UserRepository
from app.modules.users.schemas.user import SocialLogin, UserRead
from app.modules.users.services.user import UserService
from app.shared.services.activity_log_service import ActivityLogService
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)

SECONDS_PER_MINUTE = 60


class AuthService:
    """Issues, renews and revokes the tokens that represent a signed-in user."""

    #: Which social action a provider's sign-in is recorded as. Named per
    #: provider rather than as one `social_login`, because "who has been
    #: signing in through Facebook" is a question an auditor actually asks.
    SOCIAL_ACTIONS = {
        AuthProvider.GOOGLE: ActivityAction.GOOGLE_LOGIN,
        AuthProvider.FACEBOOK: ActivityAction.FACEBOOK_LOGIN,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.AUTH)

    # -- Signing in -----------------------------------------------------

    async def login(
        self, payload: LoginRequest, context: SessionContext | None = None
    ) -> AuthenticatedUser:
        """Verify a password and open a session.

        Accepts an email address or a phone number in the same field; the
        repository works out which was given.
        """
        user = await self.users.get_by_identifier(payload.identifier)

        if user is None:
            # Still pay for a hash, so a missing account is not measurably
            # faster to reject than a wrong password.
            dummy_verify(payload.password)
            await self._record_refusal(
                f"Failed sign-in: no account for '{payload.identifier}'"
            )
            raise UnauthorizedException(INVALID_CREDENTIALS_MESSAGE)

        if not verify_password(payload.password, user.password_hash):
            logger.info("Failed sign-in for user %s", user.id)
            await self._record_refusal(
                f"Failed sign-in: wrong password for {payload.identifier}", user=user
            )
            raise UnauthorizedException(INVALID_CREDENTIALS_MESSAGE)

        # Only once the password is proven, so account state never leaks to
        # someone who could not sign in anyway.
        try:
            self._guard_can_sign_in(user)
        except (ForbiddenException, UnauthorizedException):
            await self._record_refusal(
                f"Refused sign-in: account is {user.status}", user=user
            )
            raise

        await self.users.update(user, last_login_at=utc_now())
        pair = await self._issue_tokens(user, context)

        await self.activity.record(
            ActivityAction.LOGIN,
            entity=user,
            description=f"{user.full_name} signed in",
            actor=user,
            new_values={"identifier": payload.identifier, "method": "password"},
        )
        await self.session.commit()

        logger.info("User %s signed in", user.id)
        return self._authenticated(user, pair)

    async def social_login(
        self, payload: SocialLogin, context: SessionContext | None = None
    ) -> tuple[AuthenticatedUser, bool]:
        """Open a session from a verified Google or Facebook identity.

        The provider's token must already have been validated with the
        provider - this trusts what it is handed. Returns the session and
        whether the account was created by this sign-in.

        No password is involved, which is the point: an account created this
        way has none until the user sets one.
        """
        user, created = await UserService(self.session).resolve_social_login(payload)

        try:
            self._guard_can_sign_in(user)
        except (ForbiddenException, UnauthorizedException):
            await self._record_refusal(
                f"Refused {payload.provider.value} sign-in: account is {user.status}",
                user=user,
                action=self.SOCIAL_ACTIONS.get(
                    payload.provider, ActivityAction.SOCIAL_LOGIN
                ),
            )
            raise

        await self.users.update(user, last_login_at=utc_now())
        pair = await self._issue_tokens(user, context)

        await self.activity.record(
            self.SOCIAL_ACTIONS.get(payload.provider, ActivityAction.SOCIAL_LOGIN),
            entity=user,
            description=(
                f"{user.full_name} signed in with {payload.provider.value}"
                + (" for the first time, creating the account" if created else "")
            ),
            actor=user,
            new_values={
                "provider": payload.provider.value,
                "account_created": created,
            },
        )
        await self.session.commit()

        logger.info("User %s signed in via %s", user.id, payload.provider.value)
        return self._authenticated(user, pair), created

    # -- Renewing -------------------------------------------------------

    async def refresh(
        self, refresh_token: str, context: SessionContext | None = None
    ) -> TokenPair:
        """Trade a refresh token for a fresh pair, retiring the old one.

        Rotation on every use means a stolen token has value only until the
        real client next refreshes, and it turns theft into something the
        server can notice - see the reuse branch below.
        """
        claims = self._decode(refresh_token, TokenType.REFRESH)
        stored = await self.tokens.get_by_fingerprint(token_fingerprint(refresh_token))

        if stored is None:
            # Correctly signed but no session behind it: the row was purged
            # long after expiry, or the token was never ours to begin with.
            raise UnauthorizedException("This session is no longer valid.")

        if stored.revoked_reason == RevocationReason.ROTATED:
            # A rotated token was spent the moment it was used. Seeing it
            # again means two parties hold it, and there is no way to tell the
            # thief from the real user - so every session ends and the real
            # user signs in again.
            logger.warning(
                "Refresh token reuse detected for user %s, revoking all sessions",
                stored.user_id,
            )
            ended = await self.tokens.revoke_all_for_user(
                stored.user_id, RevocationReason.REUSE_DETECTED
            )
            # Recorded in this transaction rather than detached: the revoke
            # above is committed here too, so the entry describes something
            # that really happened.
            await self.activity.record_failure(
                ActivityAction.TOKEN_REFRESH,
                entity_type="User",
                entity_id=stored.user_id,
                description=(
                    "Refresh token reuse detected; ended every session for "
                    "this account"
                ),
                new_values={
                    "reason": RevocationReason.REUSE_DETECTED,
                    "sessions_ended": ended,
                },
            )
            await self.session.commit()
            raise UnauthorizedException(
                "This session was ended for security reasons. Please sign in again."
            )

        if stored.is_revoked:
            # Ended some other way - a sign-out, or the account being closed.
            # Only rotation implies theft: a client retrying a refresh it had
            # already raced against its own logout is not an attack, and must
            # not cost the user every other device.
            raise UnauthorizedException("This session has ended. Please sign in.")

        if stored.is_expired:
            raise UnauthorizedException("This session has expired. Please sign in.")

        user = await self.users.get(claims.subject)
        if user is None:
            raise UnauthorizedException("This session is no longer valid.")

        self._guard_can_sign_in(user)

        stored.revoke(RevocationReason.ROTATED)
        pair = await self._issue_tokens(user, context or self._context_of(stored))

        await self.activity.record(
            ActivityAction.TOKEN_REFRESH,
            entity=user,
            description=f"Renewed the session of {user.full_name}",
            actor=user,
        )
        await self.session.commit()

        return pair

    # -- Signing out ----------------------------------------------------

    async def logout(self, user_id: uuid.UUID, refresh_token: str) -> None:
        """End one session.

        The token is looked up by digest rather than decoded, so a session can
        still be closed with a token that has already expired.

        Signing out of a session that is already closed is not an error - a
        client retrying a logout should not see a failure.
        """
        stored = await self.tokens.get_by_fingerprint(token_fingerprint(refresh_token))

        if stored is None or stored.user_id != user_id:
            # Either way there is nothing of this user's left to revoke.
            return

        stored.revoke(RevocationReason.LOGOUT)

        await self.activity.record(
            ActivityAction.LOGOUT,
            entity_type="User",
            entity_id=user_id,
            description="Signed out of one session",
            new_values={"sessions_ended": 1},
        )
        await self.session.commit()

        logger.info("User %s signed out of one session", user_id)

    async def logout_everywhere(self, user_id: uuid.UUID) -> int:
        """End every session. Returns how many were open."""
        ended = await self.tokens.revoke_all_for_user(
            user_id, RevocationReason.LOGOUT_ALL
        )

        await self.activity.record(
            ActivityAction.LOGOUT,
            entity_type="User",
            entity_id=user_id,
            description=f"Signed out of every session ({ended} open)",
            new_values={"sessions_ended": ended, "scope": "all"},
        )
        await self.session.commit()

        logger.info("User %s signed out of %d sessions", user_id, ended)
        return ended

    async def _record_refusal(
        self,
        description: str,
        *,
        user: User | None = None,
        action: ActivityAction = ActivityAction.LOGIN_FAILED,
    ) -> None:
        """Record a sign-in that was turned away.

        On its own session, because the caller is about to raise: the
        exception ends the request's transaction, and a refusal that
        disappears with it is exactly the entry an audit trail is kept for.
        """
        await ActivityLogService.record_detached(
            action,
            module=ActivityModule.AUTH,
            description=description,
            entity_type="User",
            entity_id=user.id if user else None,
            context=(
                get_request_context().with_actor(user)
                if user is not None
                else get_request_context()
            ),
        )

    async def list_sessions(
        self, user_id: uuid.UUID, *, active_only: bool = True
    ) -> list[RefreshToken]:
        return await self.tokens.list_for_user(user_id, active_only=active_only)

    # -- Verifying ------------------------------------------------------

    async def authenticate(self, access_token: str) -> User:
        """Resolve an access token to the user it belongs to.

        The user is loaded rather than reconstructed from claims, so roles and
        permissions are whatever they are right now. A token holds no
        authorization of its own; it only names its subject.
        """
        claims = self._decode(access_token, TokenType.ACCESS)

        # Soft-deleted users are filtered out by the repository, so a deleted
        # account stops authenticating without anyone revoking its tokens.
        user = await self.users.get(claims.subject)
        if user is None:
            raise UnauthorizedException("This account is no longer available.")

        self._guard_can_sign_in(user)
        self._guard_not_superseded(user, claims)
        return user

    @staticmethod
    def _guard_not_superseded(user: User, claims: TokenClaims) -> None:
        """Refuse a token that predates the last password change.

        Revoking refresh tokens ends a session's ability to *renew*, but the
        access token it already holds keeps working until it expires. That is
        an acceptable gap for a sign-out, and not for a password reset, where
        the whole point is to lock someone out now rather than in half an
        hour.

        `iat` is whole seconds, so the cutoff is stored truncated to the
        second to match - see `truncate_to_second`. Comparing a whole-second
        `iat` against a cutoff carrying microseconds would reject the token
        issued by signing in immediately afterwards, which is the very next
        thing someone does after resetting a password.
        """
        if user.tokens_valid_from is None:
            return

        if claims.issued_at < user.tokens_valid_from:
            raise UnauthorizedException(
                "The password for this account has changed. Please sign in again."
            )

    # -- Helpers --------------------------------------------------------

    def _decode(self, token: str, expected: TokenType) -> TokenClaims:
        """Decode a token, translating token errors into 401s."""
        try:
            return decode_token(token, expected)
        except TokenExpiredError as exc:
            raise UnauthorizedException("This token has expired.") from exc
        except TokenError as exc:
            raise UnauthorizedException("This token is not valid.") from exc

    async def issue_session(
        self, user: User, context: SessionContext | None = None
    ) -> TokenPair:
        """Open a session for a user whose identity is already established.

        Used after a password change, where the caller has just invalidated
        their own access token and needs a working one back.
        """
        pair = await self._issue_tokens(user, context)
        await self.session.commit()
        return pair

    async def _issue_tokens(
        self, user: User, context: SessionContext | None
    ) -> TokenPair:
        """Mint a pair and record the refresh half as a session."""
        access_token, access_claims = create_access_token(user.id)
        refresh_token, refresh_claims = create_refresh_token(user.id)

        await self.tokens.issue(
            user.id,
            token_hash=token_fingerprint(refresh_token),
            token_id=refresh_claims.token_id,
            expires_at=refresh_claims.expires_at,
            user_agent=context.user_agent if context else None,
            ip_address=context.ip_address if context else None,
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * SECONDS_PER_MINUTE,
            expires_at=access_claims.expires_at,
            refresh_expires_at=refresh_claims.expires_at,
        )

    def _guard_can_sign_in(self, user: User) -> None:
        """Suspended and deactivated accounts hold no sessions."""
        if not user.can_sign_in:
            raise ForbiddenException(
                f"This account is {user.status} and cannot be used to sign in."
            )

    @staticmethod
    def _context_of(stored: RefreshToken) -> SessionContext:
        """Carry a session's origin across a rotation, so it stays recognisable."""
        return SessionContext(
            user_agent=stored.user_agent, ip_address=stored.ip_address
        )

    @staticmethod
    def _authenticated(user: User, pair: TokenPair) -> AuthenticatedUser:
        return AuthenticatedUser(
            user=UserRead.model_validate(user),
            tokens=pair,
            roles=sorted(user.role_slugs),
            permissions=sorted(user.permission_codes),
        )
