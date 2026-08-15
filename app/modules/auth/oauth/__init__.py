"""OAuth 2.0 provider integrations."""

from app.modules.auth.oauth.base import (
    OAuthProvider,
    ProviderCredentials,
    SocialProfile,
)
from app.modules.auth.oauth.facebook import FacebookOAuthProvider
from app.modules.auth.oauth.google import GoogleOAuthProvider

__all__ = [
    "FacebookOAuthProvider",
    "GoogleOAuthProvider",
    "OAuthProvider",
    "ProviderCredentials",
    "SocialProfile",
]
