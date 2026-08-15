"""Tests for the authentication module."""

import uuid
from collections.abc import AsyncIterator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import TokenType
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify,
    token_fingerprint,
)
from app.modules.auth.constants import RevocationReason
from app.modules.auth.dependencies import require_permission, require_role
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.auth.schemas.auth import LoginRequest, SessionContext
from app.modules.auth.services.auth import AuthService
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import AuthProvider, UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import SocialLogin, UserCreate
from app.modules.users.services.user import UserService
from app.shared.utils.dates import utc_now

PASSWORD = "AuthTest#2026"
EMAIL = "signin@bwin.example.com"
PHONE = "+8801799000001"


@pytest.fixture
async def auth(session: AsyncSession) -> AsyncIterator[AuthService]:
    """Roles, permissions and a clean session table, restored afterwards."""

    async def wipe() -> None:
        await session.execute(delete(RefreshToken))
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.commit()

    await wipe()
    await RoleService(session).seed_system_roles()
    await PermissionService(session).seed_system_permissions()
    await PermissionService(session).seed_default_role_permissions()

    yield AuthService(session)

    await wipe()


async def make_user(
    session: AsyncSession,
    *,
    email: str = EMAIL,
    phone: str | None = PHONE,
    password: str | None = PASSWORD,
    status: UserStatus = UserStatus.ACTIVE,
    role: str = "instructor",
) -> User:
    role_id = await RoleRepository(session).get_by_slug(role)
    assert role_id is not None

    return await UserService(session).create(
        UserCreate(
            email=email,
            phone=phone,
            password=password,
            first_name="Sign",
            last_name="In",
            status=status,
            role_ids=[role_id.id],
        )
    )


@pytest.fixture
async def account(auth: AuthService, session: AsyncSession) -> User:
    return await make_user(session)


# -- Token primitives ---------------------------------------------------


def test_access_token_round_trip() -> None:
    subject = uuid.uuid4()

    token, issued = create_access_token(subject)
    claims = decode_token(token, TokenType.ACCESS)

    assert claims.subject == subject
    assert claims.token_type is TokenType.ACCESS
    assert claims.token_id == issued.token_id
    assert claims.expires_at > claims.issued_at


def test_refresh_token_carries_the_longer_lifetime() -> None:
    _, access = create_access_token(uuid.uuid4())
    _, refresh = create_refresh_token(uuid.uuid4())

    assert refresh.expires_at > access.expires_at


def test_a_refresh_token_is_not_accepted_as_an_access_token() -> None:
    """Otherwise a stolen refresh token would grant API access outright."""
    token, _ = create_refresh_token(uuid.uuid4())

    with pytest.raises(InvalidTokenError):
        decode_token(token, TokenType.ACCESS)


def test_each_token_gets_its_own_id() -> None:
    """The `jti` is what makes one session distinguishable from another."""
    _, first = create_refresh_token(uuid.uuid4())
    _, second = create_refresh_token(uuid.uuid4())

    assert first.token_id != second.token_id


def test_a_tampered_token_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4())
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")

    with pytest.raises(InvalidTokenError):
        decode_token(tampered)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "jti": "x",
            "type": "access",
            "iat": utc_now(),
            "exp": utc_now().replace(year=utc_now().year + 1),
        },
        "not-our-secret",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_token(forged)


def test_an_unsigned_token_is_rejected() -> None:
    """`alg: none` is the classic JWT bypass; naming the algorithm blocks it."""
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "jti": "x", "type": "access"},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidTokenError):
        decode_token(unsigned)


def test_a_token_missing_claims_is_rejected() -> None:
    """A missing claim must fail, not read as `None`."""
    incomplete = jwt.encode(
        {"sub": str(uuid.uuid4())},
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_token(incomplete)


def test_an_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    token, _ = create_access_token(uuid.uuid4())

    with pytest.raises(TokenExpiredError):
        decode_token(token, TokenType.ACCESS)


def test_fingerprints_are_stable_and_hide_the_token() -> None:
    token, _ = create_refresh_token(uuid.uuid4())

    assert token_fingerprint(token) == token_fingerprint(token)
    assert len(token_fingerprint(token)) == 64
    assert token not in token_fingerprint(token)


def test_dummy_verify_never_succeeds_or_raises() -> None:
    assert dummy_verify("anything at all") is None


# -- Signing in ---------------------------------------------------------


async def test_login_with_an_email_returns_a_token_pair(
    auth: AuthService, account: User
) -> None:
    result = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    assert result.user.id == account.id
    assert result.tokens.access_token
    assert result.tokens.refresh_token
    assert result.tokens.token_type == "Bearer"
    assert result.tokens.expires_in == settings.access_token_expire_minutes * 60


async def test_login_with_a_phone_number_reaches_the_same_account(
    auth: AuthService, account: User
) -> None:
    """The whole point of the identifier field: either credential works."""
    result = await auth.login(LoginRequest(identifier=PHONE, password=PASSWORD))

    assert result.user.id == account.id


async def test_login_accepts_a_locally_formatted_phone_number(
    auth: AuthService, account: User
) -> None:
    """What a Bangladeshi user actually types, rather than E.164."""
    result = await auth.login(LoginRequest(identifier="01799000001", password=PASSWORD))

    assert result.user.id == account.id


async def test_login_returns_roles_and_permissions(
    auth: AuthService, account: User
) -> None:
    """So a client can render its navigation without a second request."""
    result = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    assert result.roles == ["instructor"]
    assert "course.create" in result.permissions
    assert "user.delete" not in result.permissions


async def test_login_records_the_moment(auth: AuthService, account: User) -> None:
    assert account.last_login_at is None

    await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    assert account.last_login_at is not None


async def test_login_with_the_wrong_password_is_refused(
    auth: AuthService, account: User
) -> None:
    with pytest.raises(UnauthorizedException):
        await auth.login(LoginRequest(identifier=EMAIL, password="not-the-password"))


async def test_an_unknown_account_fails_identically_to_a_wrong_password(
    auth: AuthService, account: User
) -> None:
    """Differing messages would confirm which addresses are registered."""
    with pytest.raises(UnauthorizedException) as unknown:
        await auth.login(
            LoginRequest(identifier="nobody@bwin.example.com", password=PASSWORD)
        )

    with pytest.raises(UnauthorizedException) as wrong:
        await auth.login(LoginRequest(identifier=EMAIL, password="wrong"))

    assert unknown.value.message == wrong.value.message


async def test_a_social_only_account_cannot_sign_in_with_a_password(
    auth: AuthService, session: AsyncSession
) -> None:
    """No password hash means the check fails rather than crashes."""
    await make_user(session, email="social@bwin.example.com", phone=None, password=None)

    with pytest.raises(UnauthorizedException):
        await auth.login(
            LoginRequest(identifier="social@bwin.example.com", password=PASSWORD)
        )


async def test_a_suspended_account_is_refused_with_a_reason(
    auth: AuthService, session: AsyncSession
) -> None:
    """The password was right, so saying why leaks nothing."""
    await make_user(
        session,
        email="blocked@bwin.example.com",
        phone=None,
        status=UserStatus.SUSPENDED,
    )

    with pytest.raises(ForbiddenException) as failure:
        await auth.login(
            LoginRequest(identifier="blocked@bwin.example.com", password=PASSWORD)
        )

    assert "suspended" in failure.value.message


async def test_login_opens_a_session_record(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    await auth.login(
        LoginRequest(identifier=EMAIL, password=PASSWORD),
        SessionContext(user_agent="pytest", ip_address="203.0.113.9"),
    )

    sessions = await auth.list_sessions(account.id)

    assert len(sessions) == 1
    assert sessions[0].user_agent == "pytest"
    assert sessions[0].ip_address == "203.0.113.9"
    assert sessions[0].is_active is True


async def test_the_stored_session_does_not_hold_the_token(
    auth: AuthService, account: User
) -> None:
    """A database dump must not hand over usable sessions."""
    result = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    stored = (await auth.list_sessions(account.id))[0]

    assert stored.token_hash != result.tokens.refresh_token
    assert stored.token_hash == token_fingerprint(result.tokens.refresh_token)


# -- Social sign-in -----------------------------------------------------


async def test_social_login_creates_an_account_on_first_use(
    auth: AuthService,
) -> None:
    result, created = await auth.social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-auth-1",
            email="new.google@bwin.example.com",
            first_name="Shafiq",
        )
    )

    assert created is True
    assert result.user.has_password is False
    assert result.tokens.access_token
    assert result.roles == ["student"]


async def test_social_login_returns_to_the_same_account(auth: AuthService) -> None:
    identity = SocialLogin(
        provider=AuthProvider.FACEBOOK,
        provider_user_id="fb-auth-1",
        email="returning@bwin.example.com",
        first_name="Rina",
    )

    first, created = await auth.social_login(identity)
    second, created_again = await auth.social_login(identity)

    assert created is True
    assert created_again is False
    assert first.user.id == second.user.id


async def test_social_login_links_to_an_account_holding_that_email(
    auth: AuthService, account: User
) -> None:
    """The provider verified the address, so this is the same person."""
    result, created = await auth.social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-auth-2",
            email=EMAIL,
        )
    )

    assert created is False
    assert result.user.id == account.id


# -- Refreshing ---------------------------------------------------------


async def test_refresh_returns_a_new_pair(auth: AuthService, account: User) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    renewed = await auth.refresh(signed_in.tokens.refresh_token)

    assert renewed.refresh_token != signed_in.tokens.refresh_token
    assert decode_token(renewed.access_token, TokenType.ACCESS).subject == account.id


async def test_refreshing_retires_the_token_it_was_given(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    await auth.refresh(signed_in.tokens.refresh_token)
    retired = await auth.tokens.get_by_fingerprint(
        token_fingerprint(signed_in.tokens.refresh_token)
    )

    assert retired is not None
    assert retired.is_revoked is True
    assert retired.revoked_reason == RevocationReason.ROTATED


async def test_reusing_a_retired_token_ends_every_session(
    auth: AuthService, account: User
) -> None:
    """Two parties holding one token means it leaked; nobody keeps the session."""
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    renewed = await auth.refresh(signed_in.tokens.refresh_token)

    with pytest.raises(UnauthorizedException):
        await auth.refresh(signed_in.tokens.refresh_token)

    # The token the honest client is holding is gone too - it cannot be told
    # apart from the thief's.
    with pytest.raises(UnauthorizedException):
        await auth.refresh(renewed.refresh_token)

    assert await auth.list_sessions(account.id) == []


async def test_reuse_detection_records_why(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    await auth.refresh(signed_in.tokens.refresh_token)

    with pytest.raises(UnauthorizedException):
        await auth.refresh(signed_in.tokens.refresh_token)

    reasons = await session.execute(
        select(RefreshToken.revoked_reason).where(RefreshToken.user_id == account.id)
    )

    assert RevocationReason.REUSE_DETECTED in set(reasons.scalars().all())


async def test_an_access_token_cannot_be_used_to_refresh(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    with pytest.raises(UnauthorizedException):
        await auth.refresh(signed_in.tokens.access_token)


async def test_a_refresh_token_with_no_session_behind_it_is_refused(
    auth: AuthService, account: User
) -> None:
    """Correctly signed, but the row was purged - there is no session left."""
    orphan, _ = create_refresh_token(account.id)

    with pytest.raises(UnauthorizedException):
        await auth.refresh(orphan)


async def test_an_expired_session_cannot_be_refreshed(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    stored = (await auth.list_sessions(account.id))[0]

    stored.expires_at = utc_now().replace(year=utc_now().year - 1)
    await session.commit()

    with pytest.raises(UnauthorizedException):
        await auth.refresh(signed_in.tokens.refresh_token)


async def test_refresh_is_refused_once_the_account_is_suspended(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    """Suspending someone must not leave them a working session."""
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    account.status = UserStatus.SUSPENDED
    await session.commit()

    with pytest.raises(ForbiddenException):
        await auth.refresh(signed_in.tokens.refresh_token)


async def test_rotation_carries_the_device_details_over(
    auth: AuthService, account: User
) -> None:
    """A refresh continues a session, so it must not look like a new device."""
    signed_in = await auth.login(
        LoginRequest(identifier=EMAIL, password=PASSWORD),
        SessionContext(user_agent="Firefox", ip_address="203.0.113.4"),
    )

    # Refreshed without a context, as a token-only client would.
    await auth.refresh(signed_in.tokens.refresh_token)
    current = (await auth.list_sessions(account.id))[0]

    assert current.user_agent == "Firefox"
    assert current.ip_address == "203.0.113.4"


# -- Signing out --------------------------------------------------------


async def test_logout_revokes_that_session(auth: AuthService, account: User) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    await auth.logout(account.id, signed_in.tokens.refresh_token)

    assert await auth.list_sessions(account.id) == []


async def test_a_revoked_session_cannot_be_refreshed(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    await auth.logout(account.id, signed_in.tokens.refresh_token)

    with pytest.raises(UnauthorizedException):
        await auth.refresh(signed_in.tokens.refresh_token)


async def test_refreshing_after_a_sign_out_does_not_end_other_sessions(
    auth: AuthService, account: User
) -> None:
    """Only rotation implies theft.

    A client can race its own sign-out and retry a refresh a moment later.
    Treating that as a stolen token would sign the user out of every other
    device for what is an ordinary timing accident.
    """
    laptop = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    phone = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    await auth.logout(account.id, phone.tokens.refresh_token)

    with pytest.raises(UnauthorizedException) as refused:
        await auth.refresh(phone.tokens.refresh_token)

    assert "security" not in refused.value.message
    assert len(await auth.list_sessions(account.id)) == 1
    # The laptop is untouched and still refreshes.
    assert await auth.refresh(laptop.tokens.refresh_token)


async def test_logout_leaves_other_sessions_alone(
    auth: AuthService, account: User
) -> None:
    """Signing out of a phone must not sign the laptop out too."""
    laptop = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    phone = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    await auth.logout(account.id, phone.tokens.refresh_token)
    remaining = await auth.list_sessions(account.id)

    assert len(remaining) == 1
    assert remaining[0].token_hash == token_fingerprint(laptop.tokens.refresh_token)


async def test_logging_out_twice_is_not_an_error(
    auth: AuthService, account: User
) -> None:
    """A client retrying a sign-out should not see a failure."""
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    await auth.logout(account.id, signed_in.tokens.refresh_token)
    await auth.logout(account.id, signed_in.tokens.refresh_token)

    assert await auth.list_sessions(account.id) == []


async def test_logout_ignores_a_token_belonging_to_someone_else(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    other = await make_user(session, email="other@bwin.example.com", phone=None)
    theirs = await auth.login(
        LoginRequest(identifier="other@bwin.example.com", password=PASSWORD)
    )

    await auth.logout(account.id, theirs.tokens.refresh_token)

    assert len(await auth.list_sessions(other.id)) == 1


async def test_logout_everywhere_ends_every_session(
    auth: AuthService, account: User
) -> None:
    for _ in range(3):
        await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    ended = await auth.logout_everywhere(account.id)

    assert ended == 3
    assert await auth.list_sessions(account.id) == []


async def test_logout_everywhere_with_no_sessions_ends_nothing(
    auth: AuthService, account: User
) -> None:
    assert await auth.logout_everywhere(account.id) == 0


async def test_ended_sessions_are_kept_for_auditing(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    await auth.logout(account.id, signed_in.tokens.refresh_token)

    history = await auth.list_sessions(account.id, active_only=False)

    assert len(history) == 1
    assert history[0].revoked_reason == RevocationReason.LOGOUT


# -- Verifying an access token ------------------------------------------


async def test_an_access_token_resolves_to_its_user(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    resolved = await auth.authenticate(signed_in.tokens.access_token)

    assert resolved.id == account.id


async def test_authentication_reflects_roles_as_they_are_now(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    """Roles are read from the database, not from claims baked into the token."""
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    admin = await RoleRepository(session).get_by_slug("admin")
    assert admin is not None
    await UserService(session).replace_roles(account.id, [admin.id])

    resolved = await auth.authenticate(signed_in.tokens.access_token)

    assert resolved.role_slugs == {"admin"}
    assert resolved.has_permission("user.delete") is True


async def test_a_deleted_account_stops_authenticating(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    """No token revocation needed: the user simply cannot be loaded."""
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))
    await UserService(session).delete(account.id)

    with pytest.raises(UnauthorizedException):
        await auth.authenticate(signed_in.tokens.access_token)


async def test_a_suspended_account_stops_authenticating(
    auth: AuthService, account: User, session: AsyncSession
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    account.status = UserStatus.SUSPENDED
    await session.commit()

    with pytest.raises(ForbiddenException):
        await auth.authenticate(signed_in.tokens.access_token)


async def test_a_refresh_token_is_not_accepted_as_a_credential(
    auth: AuthService, account: User
) -> None:
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=PASSWORD))

    with pytest.raises(UnauthorizedException):
        await auth.authenticate(signed_in.tokens.refresh_token)


# -- Authorization guards -----------------------------------------------


async def test_a_permission_guard_lets_a_holder_through(account: User) -> None:
    guard = require_permission("course.create")

    assert await guard(account) is account


async def test_a_permission_guard_names_what_is_missing(account: User) -> None:
    """An opaque 403 leaves a client with nowhere to go."""
    guard = require_permission("user.delete")

    with pytest.raises(ForbiddenException) as refusal:
        await guard(account)

    assert "user.delete" in refusal.value.message


async def test_a_permission_guard_can_require_every_code(account: User) -> None:
    guard = require_permission("course.create", "user.delete")

    with pytest.raises(ForbiddenException):
        await guard(account)


async def test_a_permission_guard_can_accept_any_code(account: User) -> None:
    guard = require_permission("course.create", "user.delete", require_all=False)

    assert await guard(account) is account


async def test_a_role_guard_checks_who_rather_than_what(account: User) -> None:
    assert await require_role("instructor")(account) is account

    with pytest.raises(ForbiddenException):
        await require_role("admin", "super-admin")(account)


# -- Through the API ----------------------------------------------------


@pytest.fixture
def api_account(client: TestClient, account: User) -> User:
    """The account above, with the app's own client pointed at the same data."""
    return account


def test_login_endpoint_returns_the_standard_envelope(
    client: TestClient, api_account: User
) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"identifier": EMAIL, "password": PASSWORD}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["message"] == "Signed in"
    assert body["data"]["tokens"]["token_type"] == "Bearer"


def test_the_login_response_never_carries_the_password_hash(
    client: TestClient, api_account: User
) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"identifier": EMAIL, "password": PASSWORD}
    )

    assert "password_hash" not in response.text


def test_me_requires_a_token(client: TestClient, api_account: User) -> None:
    response = client.get("/api/v1/auth/me")
    body = response.json()

    assert response.status_code == 401
    assert body["success"] is False
    assert body["error_code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_returns_the_signed_in_user(client: TestClient, api_account: User) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"identifier": EMAIL, "password": PASSWORD}
    ).json()["data"]["tokens"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == EMAIL


def test_a_nonsense_token_is_rejected(client: TestClient, api_account: User) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert response.status_code == 401


def test_a_wrong_password_returns_401(client: TestClient, api_account: User) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"identifier": EMAIL, "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json()["success"] is False


def test_the_full_sign_in_refresh_sign_out_cycle(
    client: TestClient, api_account: User
) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"identifier": PHONE, "password": PASSWORD}
    ).json()["data"]["tokens"]

    renewed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert renewed.status_code == 200
    new_tokens = renewed.json()["data"]

    headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
    signed_out = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_tokens["refresh_token"]},
        headers=headers,
    )
    assert signed_out.status_code == 200

    # The session is gone, so the refresh token no longer buys anything.
    after = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert after.status_code == 401


def test_sessions_endpoint_lists_the_current_device(
    client: TestClient, api_account: User
) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"identifier": EMAIL, "password": PASSWORD}
    ).json()["data"]["tokens"]

    response = client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    sessions = response.json()["data"]

    assert response.status_code == 200
    assert len(sessions) >= 1
    assert sessions[0]["is_active"] is True


def test_logout_all_reports_how_many_sessions_ended(
    client: TestClient, api_account: User
) -> None:
    for _ in range(2):
        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": EMAIL, "password": PASSWORD}
        ).json()["data"]["tokens"]

    response = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["sessions_ended"] == 2


def test_the_bearer_scheme_is_advertised_in_the_schema(client: TestClient) -> None:
    """So Swagger shows an Authorize button rather than requiring curl."""
    schema = client.get("/openapi.json").json()

    assert "Bearer" in schema["components"]["securitySchemes"]
