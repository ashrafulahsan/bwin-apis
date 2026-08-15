"""Google OAuth 2.0 / OpenID Connect."""

from app.modules.auth.oauth.base import OAuthProvider, SocialProfile
from app.modules.users.constants import AuthProvider


class GoogleOAuthProvider(OAuthProvider):
    """Sign-in through a Google account.

    Configured in the Google Cloud console under *APIs & Services →
    Credentials → OAuth 2.0 Client IDs*, with the callback URL registered
    there as an authorized redirect URI. It must match byte for byte, down to
    the trailing slash, or Google refuses the exchange.
    """

    provider = AuthProvider.GOOGLE
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    profile_url = "https://openidconnect.googleapis.com/v1/userinfo"
    scopes = ("openid", "email", "profile")

    def authorization_params(self, state: str) -> dict[str, str]:
        params = super().authorization_params(state)
        params.update(
            {
                # Without this Google returns no refresh token, and returns
                # nothing at all on a second sign-in by the same user.
                "access_type": "offline",
                # Ask again rather than silently reusing a stale grant, so a
                # user who revoked access can grant it back.
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return params

    async def fetch_profile(self, access_token: str) -> SocialProfile:
        data = await self._get(self.profile_url, access_token)

        subject = data.get("sub")
        if not subject:
            raise self._unreachable()

        return SocialProfile(
            provider=self.provider,
            provider_user_id=str(subject),
            email=str(data["email"]) if data.get("email") else None,
            first_name=str(data["given_name"]) if data.get("given_name") else None,
            last_name=str(data["family_name"]) if data.get("family_name") else None,
            avatar_url=str(data["picture"]) if data.get("picture") else None,
            # Google reports this per address; a Workspace account with an
            # unverified alias comes back false.
            email_verified=bool(data.get("email_verified")),
        )
