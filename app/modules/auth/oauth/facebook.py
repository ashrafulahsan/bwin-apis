"""Facebook Login (OAuth 2.0 over the Graph API)."""

import hashlib
import hmac

from app.modules.auth.oauth.base import OAuthProvider, SocialProfile
from app.modules.users.constants import AuthProvider

#: Pinned rather than floating. Graph deprecates versions on a schedule, and a
#: silent bump could change field names underneath a working sign-in.
GRAPH_API_VERSION = "v21.0"

#: Asked for explicitly; Graph returns almost nothing by default.
PROFILE_FIELDS = "id,email,first_name,last_name,picture.type(large)"


class FacebookOAuthProvider(OAuthProvider):
    """Sign-in through a Facebook account.

    Configured in the Meta for Developers dashboard under *Facebook Login →
    Settings*, with the callback registered as a valid OAuth redirect URI.

    Note that **an email address is not guaranteed**. An account registered
    with a phone number, or one where the user declined the email permission,
    comes back without one - which the service has to handle rather than
    assume away.
    """

    provider = AuthProvider.FACEBOOK
    authorize_url = f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth"
    token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
    profile_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/me"
    scopes = ("email", "public_profile")

    def authorization_params(self, state: str) -> dict[str, str]:
        params = super().authorization_params(state)
        # Graph wants its scopes comma-separated, not space-separated.
        params["scope"] = ",".join(self.scopes)
        return params

    async def fetch_profile(self, access_token: str) -> SocialProfile:
        data = await self._get(
            self.profile_url,
            access_token,
            params={
                "fields": PROFILE_FIELDS,
                # Proves the call comes from the server holding the app
                # secret, so a stolen user token alone cannot read profiles.
                "appsecret_proof": self._appsecret_proof(access_token),
            },
        )

        user_id = data.get("id")
        if not user_id:
            raise self._unreachable()

        return SocialProfile(
            provider=self.provider,
            provider_user_id=str(user_id),
            email=str(data["email"]) if data.get("email") else None,
            first_name=str(data["first_name"]) if data.get("first_name") else None,
            last_name=str(data["last_name"]) if data.get("last_name") else None,
            avatar_url=self._picture_url(data.get("picture")),
            # Graph exposes no verification flag, but an address only reaches
            # here once Facebook has confirmed it on the account.
            email_verified=bool(data.get("email")),
        )

    def _appsecret_proof(self, access_token: str) -> str:
        """HMAC-SHA256 of the access token, keyed with the app secret."""
        return hmac.new(
            self.credentials.client_secret.encode("utf-8"),
            access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _picture_url(picture: object) -> str | None:
        """Dig the URL out of Graph's nested picture object.

        Shaped `{"data": {"url": ..., "is_silhouette": false}}`. The silhouette
        is Facebook's blank default, which is worse than no avatar at all.
        """
        if not isinstance(picture, dict):
            return None

        data = picture.get("data")
        if not isinstance(data, dict) or data.get("is_silhouette"):
            return None

        url = data.get("url")
        return str(url) if url else None
