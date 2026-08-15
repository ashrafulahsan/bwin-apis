"""Tests for Google and Facebook sign-in.

Google and Facebook are stood in for at two different depths. Most tests
replace the provider outright, to get at our half of the flow: state and its
cookie, account linking, redirect handling, the refusal to leak tokens
off-site. The rest replace only the network, so the real request building,
decoding and error handling run against a stand-in that answers the way the
providers do - including the bodies they send when something goes wrong.
"""

import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    ServiceUnavailableException,
)
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.auth.oauth import state as oauth_state
from app.modules.auth.oauth.base import (
    OAuthProvider,
    ProviderCredentials,
    SocialProfile,
)
from app.modules.auth.oauth.facebook import FacebookOAuthProvider
from app.modules.auth.oauth.google import GoogleOAuthProvider
from app.modules.auth.services.oauth import OAuthService
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.settings.constants import SettingKey
from app.modules.settings.models.setting import Setting
from app.modules.settings.services.setting import SettingService
from app.modules.users.constants import AuthProvider, UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import SocialLogin, UserCreate
from app.modules.users.services.user import UserService

FRONTEND = "http://localhost:3000"
PASSWORD = "OAuthTest#2026"


def google_profile(**overrides: object) -> SocialProfile:
    defaults: dict[str, object] = {
        "provider": AuthProvider.GOOGLE,
        "provider_user_id": "google-oauth-1",
        "email": "oauth.user@bwin.example.com",
        "first_name": "Nadia",
        "last_name": "Hoque",
        "avatar_url": "https://lh3.googleusercontent.com/a/demo",
        "email_verified": True,
    }
    return SocialProfile(**{**defaults, **overrides})  # type: ignore[arg-type]


class StubProvider:
    """Stands in for a provider, recording what it was asked for."""

    def __init__(self, profile: SocialProfile) -> None:
        self.profile = profile
        self.codes: list[str] = []

    async def resolve(self, code: str) -> SocialProfile:
        self.codes.append(code)
        return self.profile


@pytest.fixture
async def oauth(session: AsyncSession) -> AsyncIterator[OAuthService]:
    """Google switched on and configured, on an otherwise clean database."""

    async def wipe() -> None:
        await session.execute(delete(RefreshToken))
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.execute(delete(Setting))
        await session.commit()

    await wipe()
    await RoleService(session).seed_system_roles()
    await PermissionService(session).seed_system_permissions()
    await PermissionService(session).seed_default_role_permissions()

    settings_service = SettingService(session)
    await settings_service.seed_system_settings()
    await settings_service.set_many(
        {
            SettingKey.GOOGLE_AUTH_ENABLED.value: "true",
            SettingKey.GOOGLE_CLIENT_ID.value: "test-client-id",
            SettingKey.GOOGLE_CLIENT_SECRET.value: "test-client-secret",
            SettingKey.FRONTEND_URL.value: FRONTEND,
            SettingKey.SOCIAL_LOGIN_REDIRECT_PATH.value: "/auth/callback",
        }
    )

    yield OAuthService(session)

    await wipe()


# -- Configuration comes from the settings table ------------------------


async def test_a_disabled_provider_is_refused(oauth: OAuthService) -> None:
    """Facebook ships switched off, so it must refuse until turned on."""
    with pytest.raises(ForbiddenException) as failure:
        await oauth.provider(AuthProvider.FACEBOOK)

    assert "facebook_auth_enabled" in failure.value.message


async def test_an_enabled_but_unconfigured_provider_names_what_is_missing(
    oauth: OAuthService,
) -> None:
    """Better here than as an error page on Facebook's domain."""
    await oauth.settings.set(SettingKey.FACEBOOK_AUTH_ENABLED, "true")

    with pytest.raises(BadRequestException) as failure:
        await oauth.provider(AuthProvider.FACEBOOK)

    assert "facebook_app_id" in failure.value.message
    assert "facebook_app_secret" in failure.value.message


async def test_credentials_are_read_from_the_settings_table(
    oauth: OAuthService,
) -> None:
    client = await oauth.provider(AuthProvider.GOOGLE)

    assert client.credentials.client_id == "test-client-id"
    assert client.credentials.client_secret == "test-client-secret"


async def test_changing_a_setting_takes_effect_without_a_restart(
    oauth: OAuthService,
) -> None:
    """The point of holding configuration in a table rather than in `.env`."""
    await oauth.settings.set(SettingKey.GOOGLE_CLIENT_ID, "rotated-id")

    client = await oauth.provider(AuthProvider.GOOGLE)

    assert client.credentials.client_id == "rotated-id"


async def test_the_callback_url_is_derived_when_left_blank(
    oauth: OAuthService,
) -> None:
    await oauth.settings.set(SettingKey.APP_BASE_URL, "https://api.bwin.example.com")

    url = await oauth.callback_url(AuthProvider.GOOGLE)

    assert url == "https://api.bwin.example.com/api/v1/auth/google/callback"


async def test_an_explicit_callback_url_wins(oauth: OAuthService) -> None:
    """Needed behind a proxy, where the app's own idea of its URL is wrong."""
    await oauth.settings.set(
        SettingKey.GOOGLE_CALLBACK_URL, "https://bwin.example.com/oauth/google"
    )

    assert (
        await oauth.callback_url(AuthProvider.GOOGLE)
        == "https://bwin.example.com/oauth/google"
    )


async def test_provider_status_reports_readiness_without_credentials(
    oauth: OAuthService,
) -> None:
    statuses = {status.provider: status for status in await oauth.statuses()}

    assert statuses["google"].usable is True
    assert statuses["facebook"].usable is False
    assert statuses["facebook"].missing == ["facebook_app_id", "facebook_app_secret"]
    # Nothing in the payload may carry a secret.
    assert "test-client-secret" not in str(statuses)


# -- The authorization URL ----------------------------------------------


async def test_the_authorization_url_carries_what_google_needs(
    oauth: OAuthService,
) -> None:
    url = await oauth.authorization_url(AuthProvider.GOOGLE, "state-value")
    query = parse_qs(urlparse(url).query)

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert query["client_id"] == ["test-client-id"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-value"]
    assert "email" in query["scope"][0]


async def test_the_client_secret_never_reaches_the_browser(
    oauth: OAuthService,
) -> None:
    """It belongs in the token exchange, which happens server to server."""
    url = await oauth.authorization_url(AuthProvider.GOOGLE, "state-value")

    assert "test-client-secret" not in url


def test_facebook_sends_its_scopes_comma_separated() -> None:
    """Graph wants commas where Google wants spaces."""
    client = FacebookOAuthProvider(
        ProviderCredentials("app-id", "app-secret", "https://cb.example.com")
    )

    query = parse_qs(urlparse(client.authorization_url("s")).query)

    assert query["scope"] == ["email,public_profile"]


def test_google_asks_for_consent_every_time() -> None:
    """Without it, a user who revoked access cannot grant it back."""
    client = GoogleOAuthProvider(
        ProviderCredentials("id", "secret", "https://cb.example.com")
    )

    query = parse_qs(urlparse(client.authorization_url("s")).query)

    assert query["prompt"] == ["consent"]


# -- State and its cookie -----------------------------------------------


def test_state_round_trips() -> None:
    nonce = oauth_state.new_nonce()
    state = oauth_state.issue("google", nonce, "http://localhost:3000/welcome")

    verified = oauth_state.verify(state, "google", nonce)

    assert verified.provider == "google"
    assert verified.redirect_to == "http://localhost:3000/welcome"


def test_the_nonce_itself_never_travels_through_the_provider() -> None:
    """Only its digest goes into the state, so the provider never sees it."""
    nonce = oauth_state.new_nonce()

    assert nonce not in oauth_state.issue("google", nonce)


def test_state_without_the_cookie_is_refused() -> None:
    """The attack this guard exists for: a state collected in another browser."""
    nonce = oauth_state.new_nonce()
    state = oauth_state.issue("google", nonce)

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(state, "google", None)


def test_state_with_the_wrong_nonce_is_refused() -> None:
    state = oauth_state.issue("google", oauth_state.new_nonce())

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(state, "google", oauth_state.new_nonce())


def test_a_state_issued_for_another_provider_is_refused() -> None:
    nonce = oauth_state.new_nonce()
    state = oauth_state.issue("google", nonce)

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(state, "facebook", nonce)


def test_a_forged_state_is_refused() -> None:
    import jwt

    forged = jwt.encode(
        {"type": "oauth_state", "provider": "google", "nonce_hash": "x", "exp": 9e9},
        "not-our-secret",
        algorithm="HS256",
    )

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(forged, "google", "anything")


def test_an_expired_state_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setattr(oauth_state, "STATE_TTL", timedelta(seconds=-1))
    nonce = oauth_state.new_nonce()
    state = oauth_state.issue("google", nonce)

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(state, "google", nonce)


def test_an_access_token_cannot_be_used_as_state() -> None:
    """Both are signed with the same key, so the type claim has to separate them."""
    import uuid

    from app.core.security import create_access_token

    token, _ = create_access_token(uuid.uuid4())

    with pytest.raises(oauth_state.InvalidStateError):
        oauth_state.verify(token, "google", "nonce")


# -- Registration and linking -------------------------------------------


async def test_a_first_sign_in_registers_the_account(
    oauth: OAuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubProvider(google_profile())
    monkeypatch.setattr(oauth, "provider", _returning(stub))

    result, created = await oauth.complete(AuthProvider.GOOGLE, "auth-code")

    assert created is True
    assert stub.codes == ["auth-code"]
    assert result.user.email == "oauth.user@bwin.example.com"
    assert result.user.has_password is False
    assert result.roles == ["student"]
    assert result.tokens.access_token


async def test_a_returning_user_is_not_registered_twice(
    oauth: OAuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oauth, "provider", _returning(StubProvider(google_profile())))

    first, _ = await oauth.complete(AuthProvider.GOOGLE, "code-1")
    second, created_again = await oauth.complete(AuthProvider.GOOGLE, "code-2")

    assert created_again is False
    assert first.user.id == second.user.id


async def test_the_profile_populates_the_new_account(
    oauth: OAuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oauth, "provider", _returning(StubProvider(google_profile())))

    result, _ = await oauth.complete(AuthProvider.GOOGLE, "code")

    assert result.user.first_name == "Nadia"
    assert result.user.last_name == "Hoque"
    assert result.user.avatar_url == "https://lh3.googleusercontent.com/a/demo"
    assert result.user.email_verified is True
    assert result.user.status == UserStatus.ACTIVE


async def test_a_verified_address_links_to_an_existing_account(
    oauth: OAuthService, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google vouched for the address, so this is the same person."""
    existing = await _make_password_user(session, "shared@bwin.example.com")
    monkeypatch.setattr(
        oauth,
        "provider",
        _returning(StubProvider(google_profile(email="shared@bwin.example.com"))),
    )

    result, created = await oauth.complete(AuthProvider.GOOGLE, "code")

    assert created is False
    assert result.user.id == existing.id
    assert result.user.has_password is True


async def test_an_unverified_address_is_never_linked(
    oauth: OAuthService, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anyone can put someone else's address on a profile - linking on that
    basis would hand them the account."""
    await _make_password_user(session, "victim@bwin.example.com")
    monkeypatch.setattr(
        oauth,
        "provider",
        _returning(
            StubProvider(
                google_profile(email="victim@bwin.example.com", email_verified=False)
            )
        ),
    )

    with pytest.raises(ForbiddenException) as refusal:
        await oauth.complete(AuthProvider.GOOGLE, "code")

    assert "link" in refusal.value.message


async def test_an_unverified_new_address_registers_but_stays_unverified(
    oauth: OAuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No account to take over, so registration is safe - just not trusted."""
    monkeypatch.setattr(
        oauth,
        "provider",
        _returning(StubProvider(google_profile(email_verified=False))),
    )

    result, created = await oauth.complete(AuthProvider.GOOGLE, "code")

    assert created is True
    assert result.user.email_verified is False


async def test_facebook_without_an_email_is_refused_clearly(
    oauth: OAuthService,
) -> None:
    """Graph returns no address for phone-registered accounts."""
    profile = google_profile(provider=AuthProvider.FACEBOOK, email=None)

    with pytest.raises(BadRequestException) as failure:
        oauth._to_social_login(profile)

    assert "email address" in failure.value.message


async def test_the_mirrored_columns_survive_any_order_of_links_and_unlinks(
    oauth: OAuthService, session: AsyncSession
) -> None:
    """The columns duplicate `user_identities`, so they have to be proven.

    Linking and unlinking in an awkward order is where a hand-patched copy
    would drift; recomputing from the identity rows cannot.
    """
    users = UserService(session)
    user = await _make_password_user(session, "both@bwin.example.com")

    await users.link_social_account(
        user.id, _identity(AuthProvider.GOOGLE, "g-1", "both@bwin.example.com")
    )
    await users.link_social_account(
        user.id, _identity(AuthProvider.FACEBOOK, "f-1", "both@bwin.example.com")
    )
    await _assert_columns_match_identities(session, user.id)

    # Drop the first provider, leaving the second - the case a naive
    # "set it when you link it" would get wrong.
    await users.unlink_social_account(user.id, "google")
    refreshed = await _assert_columns_match_identities(session, user.id)

    assert refreshed.google_id is None
    assert refreshed.facebook_id == "f-1"
    assert refreshed.social_provider == "facebook"
    assert refreshed.is_social_login is True

    await users.unlink_social_account(user.id, "facebook")
    stripped = await _assert_columns_match_identities(session, user.id)

    assert stripped.is_social_login is False
    assert stripped.social_provider is None


async def test_signing_in_updates_the_mirrored_social_columns(
    oauth: OAuthService, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`google_id` and friends must track the identity table, not drift."""
    monkeypatch.setattr(oauth, "provider", _returning(StubProvider(google_profile())))

    result, _ = await oauth.complete(AuthProvider.GOOGLE, "code")
    user = await UserService(session).get(result.user.id)

    assert user.google_id == "google-oauth-1"
    assert user.facebook_id is None
    assert user.social_provider == "google"
    assert user.is_social_login is True


async def test_unlinking_clears_the_mirrored_columns(
    oauth: OAuthService, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = await _make_password_user(session, "unlink@bwin.example.com")
    monkeypatch.setattr(
        oauth,
        "provider",
        _returning(StubProvider(google_profile(email="unlink@bwin.example.com"))),
    )
    await oauth.complete(AuthProvider.GOOGLE, "code")

    users = UserService(session)
    await users.unlink_social_account(existing.id, "google")
    user = await users.get(existing.id)

    assert user.google_id is None
    assert user.social_provider is None
    assert user.is_social_login is False


async def test_a_suspended_account_cannot_sign_in_through_google(
    oauth: OAuthService, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Social sign-in must not be a way around a suspension."""
    user = await _make_password_user(session, "blocked@bwin.example.com")
    monkeypatch.setattr(
        oauth,
        "provider",
        _returning(StubProvider(google_profile(email="blocked@bwin.example.com"))),
    )
    await oauth.complete(AuthProvider.GOOGLE, "code")

    user.status = UserStatus.SUSPENDED
    await session.commit()

    with pytest.raises(ForbiddenException):
        await oauth.complete(AuthProvider.GOOGLE, "code-2")


# -- Redirecting back ---------------------------------------------------


async def test_tokens_are_returned_in_the_fragment(
    oauth: OAuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fragment never reaches a server, so it stays out of logs."""
    monkeypatch.setattr(oauth, "provider", _returning(StubProvider(google_profile())))
    result, _ = await oauth.complete(AuthProvider.GOOGLE, "code")

    destination = await oauth.success_redirect(result)
    parsed = urlparse(destination)

    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost:3000"
    assert parsed.path == "/auth/callback"
    assert parsed.query == ""
    assert "access_token" in parse_qs(parsed.fragment)


async def test_an_off_site_redirect_is_refused(oauth: OAuthService) -> None:
    """An open redirect on a page carrying tokens hands them to whoever asked."""
    destination = await oauth._redirect_base("https://evil.example.com/steal")

    assert destination.startswith(FRONTEND)


async def test_a_same_origin_redirect_is_honoured(oauth: OAuthService) -> None:
    destination = await oauth._redirect_base(f"{FRONTEND}/welcome/back")

    assert destination == f"{FRONTEND}/welcome/back"


@pytest.mark.parametrize(
    "requested",
    ["//evil.example.com", "/relative/path", "javascript:alert(1)", "not a url"],
)
async def test_odd_redirect_targets_fall_back_to_the_default(
    oauth: OAuthService, requested: str
) -> None:
    assert await oauth._redirect_base(requested) == f"{FRONTEND}/auth/callback"


async def test_with_no_frontend_configured_there_is_nowhere_to_redirect(
    oauth: OAuthService,
) -> None:
    """Which is what makes the endpoint return JSON instead."""
    await oauth.settings.set(SettingKey.FRONTEND_URL, None)

    assert await oauth._redirect_base(None) == ""


# -- Provider response parsing ------------------------------------------


async def test_google_parses_its_userinfo_response() -> None:
    """The JSON Google actually returns from the userinfo endpoint."""
    client = GoogleOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    profile = await _parse(
        client,
        {
            "sub": "117554321098765432100",
            "email": "someone@gmail.com",
            "email_verified": True,
            "given_name": "Someone",
            "family_name": "Else",
            "picture": "https://lh3.googleusercontent.com/a/abc",
        },
    )

    assert profile.provider_user_id == "117554321098765432100"
    assert profile.email == "someone@gmail.com"
    assert profile.email_verified is True
    assert profile.first_name == "Someone"


async def test_google_reports_an_unverified_address_as_such() -> None:
    client = GoogleOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    profile = await _parse(
        client, {"sub": "1", "email": "alias@example.com", "email_verified": False}
    )

    assert profile.email_verified is False


async def test_facebook_parses_its_graph_response() -> None:
    client = FacebookOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    profile = await _parse(
        client,
        {
            "id": "10223344556677889",
            "email": "someone@example.com",
            "first_name": "Someone",
            "last_name": "Else",
            "picture": {
                "data": {
                    "url": "https://scontent.xx.fbcdn.net/a",
                    "is_silhouette": False,
                }
            },
        },
    )

    assert profile.provider_user_id == "10223344556677889"
    assert profile.avatar_url == "https://scontent.xx.fbcdn.net/a"


async def test_facebooks_blank_silhouette_is_not_used_as_an_avatar() -> None:
    """It is Facebook's placeholder, which is worse than showing none."""
    client = FacebookOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    profile = await _parse(
        client,
        {
            "id": "1",
            "email": "a@b.example",
            "picture": {"data": {"url": "https://x/silhouette", "is_silhouette": True}},
        },
    )

    assert profile.avatar_url is None


async def test_facebook_copes_with_a_missing_email() -> None:
    client = FacebookOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    profile = await _parse(client, {"id": "1", "first_name": "Anon"})

    assert profile.email is None
    assert profile.email_verified is False


def test_facebook_signs_its_profile_call() -> None:
    """`appsecret_proof` stops a stolen user token being used on its own."""
    client = FacebookOAuthProvider(
        ProviderCredentials("id", "app-secret", "https://cb")
    )

    proof = client._appsecret_proof("user-access-token")

    assert len(proof) == 64
    assert proof != client._appsecret_proof("another-token")


async def test_an_unusable_provider_response_is_a_503() -> None:
    """A malformed body is the provider's fault, not the caller's."""
    client = GoogleOAuthProvider(ProviderCredentials("id", "secret", "https://cb"))

    with pytest.raises(ServiceUnavailableException):
        await _parse(client, {"email": "no-subject@example.com"})


# -- The exchange over real HTTP ----------------------------------------
#
# A stand-in provider answers over `httpx`, so the request building, the
# decoding and the error handling all run for real - only the far end is ours.


def _stub_transport(
    routes: dict[str, tuple[int, object]],
    recorder: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)

        for path, (status, body) in routes.items():
            if path in str(request.url):
                if isinstance(body, str):
                    return httpx.Response(status, text=body)
                return httpx.Response(status, json=body)

        return httpx.Response(404, json={"error": "not_found"})

    return httpx.MockTransport(handle)


async def test_the_code_is_exchanged_for_a_profile() -> None:
    """The whole provider half: code in, normalized profile out."""
    requests: list[httpx.Request] = []
    client = GoogleOAuthProvider(
        ProviderCredentials("client-id", "client-secret", "https://cb.example.com"),
        transport=_stub_transport(
            {
                "oauth2.googleapis.com/token": (200, {"access_token": "at-1"}),
                "userinfo": (
                    200,
                    {"sub": "42", "email": "a@b.example", "email_verified": True},
                ),
            },
            requests,
        ),
    )

    profile = await client.resolve("the-code")

    assert profile.provider_user_id == "42"
    assert profile.email == "a@b.example"

    token_request, profile_request = requests
    body = token_request.content.decode()
    assert "code=the-code" in body
    assert "grant_type=authorization_code" in body
    assert "client_secret=client-secret" in body
    # The profile call carries the token, never the client secret.
    assert profile_request.headers["authorization"] == "Bearer at-1"
    assert "client-secret" not in str(profile_request.url)


async def test_a_rejected_code_is_reported_as_a_bad_request() -> None:
    """Usually a redirect URI mismatch, or a code already spent."""
    client = GoogleOAuthProvider(
        ProviderCredentials("id", "secret", "https://cb"),
        transport=_stub_transport(
            {
                "token": (
                    400,
                    {
                        "error": "invalid_grant",
                        "error_description": "Bad Request",
                    },
                )
            }
        ),
    )

    with pytest.raises(BadRequestException):
        await client.exchange_code("spent-code")


async def test_a_provider_outage_is_a_503_not_a_500() -> None:
    """Google being down is not this API's fault, and says so."""
    client = GoogleOAuthProvider(
        ProviderCredentials("id", "secret", "https://cb"),
        transport=_stub_transport({"token": (503, {"error": "unavailable"})}),
    )

    with pytest.raises(ServiceUnavailableException):
        await client.exchange_code("code")


async def test_a_non_json_body_does_not_crash_the_callback() -> None:
    """Providers serve HTML error pages more often than anyone expects."""
    client = GoogleOAuthProvider(
        ProviderCredentials("id", "secret", "https://cb"),
        transport=_stub_transport({"token": (200, "<html>Service Unavailable</html>")}),
    )

    with pytest.raises(ServiceUnavailableException):
        await client.exchange_code("code")


async def test_a_network_failure_is_a_503() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = GoogleOAuthProvider(
        ProviderCredentials("id", "secret", "https://cb"),
        transport=httpx.MockTransport(refuse),
    )

    with pytest.raises(ServiceUnavailableException):
        await client.exchange_code("code")


async def test_facebook_signs_the_profile_call_it_actually_sends() -> None:
    requests: list[httpx.Request] = []
    client = FacebookOAuthProvider(
        ProviderCredentials("app-id", "app-secret", "https://cb"),
        transport=_stub_transport(
            {"me": (200, {"id": "9", "email": "a@b.example"})}, requests
        ),
    )

    await client.fetch_profile("user-token")
    query = parse_qs(urlparse(str(requests[0].url)).query)

    assert query["appsecret_proof"] == [client._appsecret_proof("user-token")]
    assert "email" in query["fields"][0]


# -- Through the API ----------------------------------------------------


@pytest.fixture
def api(client: TestClient, oauth: OAuthService) -> TestClient:
    """The app's client, with Google configured in the database."""
    return client


def test_the_four_endpoints_exist(api: TestClient) -> None:
    """Exactly the routes the commit asked for."""
    paths = api.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/{provider}/login" in paths
    assert "/api/v1/auth/{provider}/callback" in paths


def test_login_redirects_to_google(api: TestClient) -> None:
    response = api.get("/api/v1/auth/google/login", follow_redirects=False)
    location = urlparse(response.headers["location"])

    assert response.status_code == 307
    assert location.netloc == "accounts.google.com"
    assert parse_qs(location.query)["client_id"] == ["test-client-id"]


def test_login_sets_the_state_cookie(api: TestClient) -> None:
    response = api.get("/api/v1/auth/google/login", follow_redirects=False)
    header = response.headers["set-cookie"]

    assert "bwin_oauth_state_google=" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")


def test_the_state_cookie_is_not_readable_by_javascript(api: TestClient) -> None:
    """An XSS bug must not be able to lift the nonce out of the browser."""
    response = api.get("/api/v1/auth/google/login", follow_redirects=False)

    assert "HttpOnly" in response.headers["set-cookie"]


def test_a_disabled_provider_refuses_to_start(api: TestClient) -> None:
    response = api.get("/api/v1/auth/facebook/login", follow_redirects=False)

    assert response.status_code == 403
    assert response.json()["success"] is False


def test_an_unknown_provider_is_not_a_route(api: TestClient) -> None:
    """`password` is an auth provider but not one a browser can be sent to."""
    assert api.get("/api/v1/auth/password/login").status_code == 422


def test_a_callback_without_state_is_refused(api: TestClient) -> None:
    response = api.get("/api/v1/auth/google/callback?code=abc", follow_redirects=False)

    assert response.status_code == 307
    assert "error" in urlparse(response.headers["location"]).fragment


def test_a_cancelled_sign_in_goes_back_to_the_frontend(api: TestClient) -> None:
    """Providers report a refusal in the query string, not by failing."""
    response = api.get(
        "/api/v1/auth/google/callback?error=access_denied", follow_redirects=False
    )
    fragment = parse_qs(urlparse(response.headers["location"]).fragment)

    assert response.status_code == 307
    assert "cancelled" in fragment["error"][0]


def test_the_providers_endpoint_is_readable_without_signing_in(
    api: TestClient,
) -> None:
    """A sign-in page needs it before anyone has a token."""
    response = api.get("/api/v1/auth/providers")
    providers = {row["provider"]: row for row in response.json()["data"]}

    assert response.status_code == 200
    assert providers["google"]["usable"] is True
    assert providers["facebook"]["enabled"] is False


def test_the_providers_endpoint_leaks_no_credentials(api: TestClient) -> None:
    response = api.get("/api/v1/auth/providers")

    assert "test-client-secret" not in response.text


def test_settings_require_permission(api: TestClient) -> None:
    """These rows hold OAuth secrets; an open settings API would leak them."""
    assert api.get("/api/v1/settings").status_code == 401
    assert api.patch("/api/v1/settings", json={"values": {}}).status_code == 401


# -- Helpers ------------------------------------------------------------


def _returning(stub: StubProvider):  # noqa: ANN202 - test helper
    async def _provider(_provider: AuthProvider) -> StubProvider:
        return stub

    return _provider


async def _parse(client: OAuthProvider, payload: dict[str, object]) -> SocialProfile:
    """Run a provider's parsing over a body, without any HTTP.

    Only `_get` is replaced, so the parsing under test is the real thing.
    """

    async def fake_get(*_args: object, **_kwargs: object) -> dict[str, object]:
        return payload

    client._get = fake_get  # type: ignore[assignment, method-assign]
    return await client.fetch_profile("token")


def _identity(provider: AuthProvider, provider_user_id: str, email: str) -> SocialLogin:
    return SocialLogin(
        provider=provider, provider_user_id=provider_user_id, email=email
    )


async def _assert_columns_match_identities(
    session: AsyncSession, user_id: uuid.UUID
) -> User:
    """The invariant: the columns are exactly what the identity rows say."""
    user = await UserService(session).get(user_id)
    by_provider = {row.provider: row.provider_user_id for row in user.identities}

    assert user.google_id == by_provider.get("google")
    assert user.facebook_id == by_provider.get("facebook")
    assert user.is_social_login is bool(by_provider)

    return user


async def _make_password_user(session: AsyncSession, email: str) -> User:
    role = await RoleRepository(session).get_by_slug("student")
    assert role is not None

    return await UserService(session).create(
        UserCreate(
            email=email,
            password=PASSWORD,
            first_name="Existing",
            status=UserStatus.ACTIVE,
            role_ids=[role.id],
        )
    )
