"""Business logic for social sign-in.

Configuration is read from the settings table on every request, so switching a
provider on, or rotating its secret, takes effect immediately and without a
deployment. Nothing here is read from the environment.
"""

import logging
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException
from app.modules.auth.oauth.base import (
    OAuthProvider,
    ProviderCredentials,
    SocialProfile,
)
from app.modules.auth.oauth.facebook import FacebookOAuthProvider
from app.modules.auth.oauth.google import GoogleOAuthProvider
from app.modules.auth.schemas.auth import AuthenticatedUser, SessionContext
from app.modules.auth.services.auth import AuthService
from app.modules.settings.constants import SettingKey
from app.modules.settings.schemas.setting import ProviderStatus
from app.modules.settings.services.setting import SettingService
from app.modules.users.constants import AuthProvider
from app.modules.users.schemas.user import SocialLogin

logger = logging.getLogger(__name__)

#: Which settings configure each provider, and which class drives it.
PROVIDER_SETTINGS: dict[AuthProvider, dict[str, str]] = {
    AuthProvider.GOOGLE: {
        "enabled": SettingKey.GOOGLE_AUTH_ENABLED.value,
        "client_id": SettingKey.GOOGLE_CLIENT_ID.value,
        "client_secret": SettingKey.GOOGLE_CLIENT_SECRET.value,
        "callback_url": SettingKey.GOOGLE_CALLBACK_URL.value,
    },
    AuthProvider.FACEBOOK: {
        "enabled": SettingKey.FACEBOOK_AUTH_ENABLED.value,
        "client_id": SettingKey.FACEBOOK_APP_ID.value,
        "client_secret": SettingKey.FACEBOOK_APP_SECRET.value,
        "callback_url": SettingKey.FACEBOOK_CALLBACK_URL.value,
    },
}

PROVIDER_CLASSES: dict[AuthProvider, type[OAuthProvider]] = {
    AuthProvider.GOOGLE: GoogleOAuthProvider,
    AuthProvider.FACEBOOK: FacebookOAuthProvider,
}


class OAuthService:
    """Runs the authorization code flow and turns its result into a session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingService(session)
        self.auth = AuthService(session)

    # -- Configuration --------------------------------------------------

    async def provider(self, provider: AuthProvider) -> OAuthProvider:
        """Build a configured provider, or explain what is missing.

        Refusing loudly here is the point: a half-configured provider that
        silently redirected to Google with an empty client id would fail on
        Google's error page, where nobody administering this platform would
        see it.
        """
        if provider not in PROVIDER_SETTINGS:
            raise BadRequestException(f"'{provider}' is not a social provider.")

        keys = PROVIDER_SETTINGS[provider]
        await self.settings.preload(*keys.values(), SettingKey.APP_BASE_URL.value)

        if not await self.settings.flag(keys["enabled"]):
            raise ForbiddenException(
                f"{provider.value.title()} sign-in is switched off. "
                f"Enable it with the '{keys['enabled']}' setting."
            )

        client_id = await self.settings.value(keys["client_id"])
        client_secret = await self.settings.value(keys["client_secret"])

        missing = [
            key
            for key, value in (
                (keys["client_id"], client_id),
                (keys["client_secret"], client_secret),
            )
            if not value
        ]
        if missing:
            raise BadRequestException(
                f"{provider.value.title()} sign-in is not configured yet. "
                f"Fill in: {', '.join(missing)}."
            )

        return PROVIDER_CLASSES[provider](
            ProviderCredentials(
                client_id=client_id,  # type: ignore[arg-type]
                client_secret=client_secret,  # type: ignore[arg-type]
                callback_url=await self.callback_url(provider),
            )
        )

    async def callback_url(self, provider: AuthProvider) -> str:
        """The redirect URI registered with the provider.

        Set explicitly when the public URL differs from what the application
        knows about itself - behind a proxy, or on a custom domain. Otherwise
        derived from the API base URL, so a working default needs one setting
        rather than three.
        """
        configured = await self.settings.value(
            PROVIDER_SETTINGS[provider]["callback_url"]
        )
        if configured:
            return configured

        base = await self.settings.require(SettingKey.APP_BASE_URL.value)
        return f"{base.rstrip('/')}/api/v1/auth/{provider.value}/callback"

    async def status(self, provider: AuthProvider) -> ProviderStatus:
        """Whether a provider is ready, without exposing its credentials.

        A sign-in page uses this to decide which buttons to show, so it is
        readable without authentication - it reveals only what a visitor
        would learn from seeing the buttons anyway.
        """
        keys = PROVIDER_SETTINGS[provider]
        await self.settings.preload(*keys.values(), SettingKey.APP_BASE_URL.value)

        enabled = await self.settings.flag(keys["enabled"])
        missing = [
            key
            for key in (keys["client_id"], keys["client_secret"])
            if not await self.settings.value(key)
        ]

        callback: str | None
        try:
            callback = await self.callback_url(provider)
        except BadRequestException:
            callback = None

        return ProviderStatus(
            provider=provider.value,
            enabled=enabled,
            configured=not missing,
            usable=enabled and not missing,
            callback_url=callback,
            missing=missing,
        )

    async def statuses(self) -> list[ProviderStatus]:
        return [await self.status(provider) for provider in PROVIDER_SETTINGS]

    # -- The flow -------------------------------------------------------

    async def authorization_url(self, provider: AuthProvider, state: str) -> str:
        """Where to send the browser to begin."""
        client = await self.provider(provider)
        return client.authorization_url(state)

    async def complete(
        self,
        provider: AuthProvider,
        code: str,
        context: SessionContext | None = None,
    ) -> tuple[AuthenticatedUser, bool]:
        """Exchange the code, then create or link the account and sign it in.

        Returns the session and whether the account was newly registered.
        """
        client = await self.provider(provider)
        profile = await client.resolve(code)

        payload = self._to_social_login(profile)

        # The sign-in itself is recorded by `social_login`, as `google_login`
        # or `facebook_login`. Nothing is logged here on purpose: this method
        # is one step of that action, and a second entry would report one
        # sign-in twice.
        result, created = await self.auth.social_login(payload, context)

        logger.info(
            "%s sign-in %s user %s",
            provider.value,
            "registered" if created else "returned",
            result.user.id,
        )
        return result, created

    @staticmethod
    def _to_social_login(profile: SocialProfile) -> SocialLogin:
        """Normalize a provider profile into the users module's shape."""
        if not profile.email and profile.provider is AuthProvider.FACEBOOK:
            # Facebook accounts registered with a phone number, or where the
            # email permission was declined, arrive without one. There is then
            # no identifier to satisfy the users table's CHECK constraint.
            raise BadRequestException(
                "Facebook did not share an email address for this account. "
                "Sign up with an email address or phone number instead."
            )

        return SocialLogin(
            provider=profile.provider,
            provider_user_id=profile.provider_user_id,
            email=profile.email,
            first_name=profile.first_name,
            last_name=profile.last_name,
            avatar_url=profile.avatar_url,
            email_verified=profile.email_verified,
        )

    # -- Redirecting back to the frontend -------------------------------

    async def success_redirect(
        self, result: AuthenticatedUser, requested: str | None = None
    ) -> str:
        """Where to send the browser once the sign-in worked.

        Tokens travel in the URL **fragment**, not the query string. A
        fragment is never sent to a server, so it stays out of access logs,
        `Referer` headers and proxy records - the query string would be in all
        three.
        """
        base = await self._redirect_base(requested)
        tokens = result.tokens

        return self._with_fragment(
            base,
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": str(tokens.expires_in),
            },
        )

    async def failure_redirect(self, message: str, requested: str | None = None) -> str:
        """Where to send the browser when the sign-in did not work."""
        return self._with_fragment(
            await self._redirect_base(requested), {"error": message}
        )

    async def _redirect_base(self, requested: str | None) -> str:
        """Resolve the post-sign-in URL, refusing to bounce anywhere else.

        A redirect target taken from a query parameter is an open redirect
        unless it is checked, and an open redirect on a page that carries
        tokens hands them to whoever asked. So a requested target is honoured
        only when it sits on the configured frontend's origin.
        """
        frontend = await self.settings.value(SettingKey.FRONTEND_URL.value)
        path = await self.settings.value(
            SettingKey.SOCIAL_LOGIN_REDIRECT_PATH.value, "/"
        )

        if not frontend:
            return ""

        default = f"{frontend.rstrip('/')}{path or '/'}"

        if not requested:
            return default

        if self._same_origin(requested, frontend):
            return requested

        logger.warning("Refused off-site sign-in redirect to %s", requested)
        return default

    @staticmethod
    def _same_origin(candidate: str, frontend: str) -> bool:
        target = urlparse(candidate)
        allowed = urlparse(frontend)

        if not target.scheme or not target.netloc:
            return False

        return (target.scheme, target.netloc) == (allowed.scheme, allowed.netloc)

    @staticmethod
    def _with_fragment(url: str, values: dict[str, str]) -> str:
        """Attach values to a URL's fragment, replacing any already there."""
        if not url:
            return ""

        scheme, netloc, path, query, _ = urlsplit(url)
        return urlunsplit((scheme, netloc, path, query, urlencode(values)))
