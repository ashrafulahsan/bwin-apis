"""The shape every OAuth 2.0 provider takes.

Google and Facebook both run the authorization code flow, and differ only in
their endpoints, their scopes and the shape of the profile they hand back. A
common base keeps those differences in one small subclass each, and gives the
service a single type to work against.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.modules.users.constants import AuthProvider

logger = logging.getLogger(__name__)

#: Provider calls are server-to-server and should be quick. A stuck request
#: must not hold a worker open waiting on someone else's outage.
PROVIDER_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ProviderCredentials:
    """What an administrator filled in for one provider."""

    client_id: str
    client_secret: str
    callback_url: str


@dataclass(frozen=True)
class SocialProfile:
    """The account a provider says is signing in.

    Normalized across providers, so the service that creates or links a user
    never has to know whose JSON it came from.
    """

    provider: AuthProvider
    provider_user_id: str
    email: str | None
    first_name: str | None
    last_name: str | None
    avatar_url: str | None
    #: Whether the provider states the address has been verified. An
    #: unverified address must not be trusted to match an existing account -
    #: anyone could claim it.
    email_verified: bool


class OAuthProvider(ABC):
    """One social identity provider."""

    provider: AuthProvider
    authorize_url: str
    token_url: str
    profile_url: str
    scopes: tuple[str, ...]

    def __init__(
        self,
        credentials: ProviderCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        # Left as `None` in production, where `httpx` picks its own. Injectable
        # so the exchange can be tested against a stand-in provider without
        # reaching out to Google.
        self.transport = transport

    # -- Step 1: send the user to the provider --------------------------

    def authorization_url(self, state: str) -> str:
        """Where the browser is sent to sign in.

        `state` travels to the provider and comes back unchanged, which is
        what ties the callback to the request that started it.
        """
        return f"{self.authorize_url}?{urlencode(self.authorization_params(state))}"

    def authorization_params(self, state: str) -> dict[str, str]:
        return {
            "client_id": self.credentials.client_id,
            "redirect_uri": self.credentials.callback_url,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
        }

    # -- Step 2: turn the code into a profile ---------------------------

    async def exchange_code(self, code: str) -> str:
        """Trade the one-time code for an access token.

        This call carries the client secret, which is why it happens here on
        the server and never in the browser.
        """
        payload = {
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret,
            "code": code,
            "redirect_uri": self.credentials.callback_url,
            "grant_type": "authorization_code",
        }

        data = await self._post(self.token_url, payload)

        token = data.get("access_token")
        if not token:
            # Usually a redirect URI that does not match the one registered,
            # or a code already spent.
            logger.warning(
                "%s returned no access token: %s",
                self.provider.value,
                data.get("error_description") or data.get("error"),
            )
            raise BadRequestException(
                f"{self.provider.value.title()} did not accept the sign-in. "
                "Please try again."
            )

        return str(token)

    @abstractmethod
    async def fetch_profile(self, access_token: str) -> SocialProfile:
        """Read the signed-in account from the provider."""

    async def resolve(self, code: str) -> SocialProfile:
        """The whole exchange: code in, verified profile out."""
        return await self.fetch_profile(await self.exchange_code(code))

    # -- HTTP -----------------------------------------------------------

    async def _post(self, url: str, payload: dict[str, str]) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=PROVIDER_TIMEOUT_SECONDS, transport=self.transport
        ) as client:
            try:
                response = await client.post(
                    url, data=payload, headers={"Accept": "application/json"}
                )
            except httpx.HTTPError as exc:
                raise self._unreachable() from exc

        return self._decode(response)

    async def _get(
        self, url: str, token: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=PROVIDER_TIMEOUT_SECONDS, transport=self.transport
        ) as client:
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise self._unreachable() from exc

        return self._decode(response)

    def _decode(self, response: httpx.Response) -> dict[str, object]:
        """Read a provider's JSON, whatever it decided to send."""
        try:
            data = response.json()
        except ValueError:
            logger.warning(
                "%s returned %s with a non-JSON body",
                self.provider.value,
                response.status_code,
            )
            raise self._unreachable() from None

        if not isinstance(data, dict):
            raise self._unreachable()

        # 4xx bodies carry the useful error text, so they are decoded before
        # the status is judged.
        if response.is_success:
            return data

        logger.warning(
            "%s returned %s: %s", self.provider.value, response.status_code, data
        )

        if response.is_server_error:
            raise self._unreachable()

        return data

    def _unreachable(self) -> ServiceUnavailableException:
        return ServiceUnavailableException(
            f"{self.provider.value.title()} could not be reached. "
            "Please try again in a moment."
        )
