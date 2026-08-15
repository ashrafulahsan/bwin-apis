"""Tests for password recovery.

The property most of these defend is that the request endpoint gives nothing
away: an unknown address, a suspended account and a throttled one all have to
come out looking identical from the outside.
"""

import re
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security import token_fingerprint, verify_password
from app.modules.auth.constants import (
    PASSWORD_RESET_MAX_PER_HOUR,
    RESET_REQUESTED_MESSAGE,
    RevocationReason,
)
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.auth.schemas.auth import LoginRequest, SessionContext
from app.modules.auth.services.auth import AuthService
from app.modules.auth.services.password_reset import PasswordResetService
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.settings.constants import SettingKey
from app.modules.settings.models.setting import Setting
from app.modules.settings.services.setting import SettingService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import UserCreate
from app.modules.users.services.user import UserService

OLD_PASSWORD = "ResetTest#2026"
NEW_PASSWORD = "BrandNew#2026"
EMAIL = "locked.out@bwin.example.com"
PHONE = "+8801788000001"
FRONTEND = "http://localhost:3000"


class RecordingSender:
    """Stands in for the mail transport, keeping what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[User, str, str]] = []

    async def send(self, user: User, link: str, *, via: str) -> None:
        self.sent.append((user, link, via))

    @property
    def last_link(self) -> str:
        return self.sent[-1][1]

    @property
    def last_token(self) -> str:
        match = re.search(r"token=([\w\-]+)", self.last_link)
        assert match is not None, f"no token in {self.last_link}"
        return match.group(1)


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
async def resets(
    session: AsyncSession, sender: RecordingSender
) -> AsyncIterator[PasswordResetService]:
    async def wipe() -> None:
        await session.execute(delete(PasswordResetToken))
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
    await settings_service.set(SettingKey.FRONTEND_URL, FRONTEND)

    yield PasswordResetService(session, sender)

    await wipe()


async def make_user(
    session: AsyncSession,
    *,
    email: str = EMAIL,
    phone: str | None = PHONE,
    password: str | None = OLD_PASSWORD,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    role = await RoleRepository(session).get_by_slug("student")
    assert role is not None

    return await UserService(session).create(
        UserCreate(
            email=email,
            phone=phone,
            password=password,
            first_name="Locked",
            last_name="Out",
            status=status,
            role_ids=[role.id],
        )
    )


@pytest.fixture
async def account(resets: PasswordResetService, session: AsyncSession) -> User:
    return await make_user(session)


# -- Requesting a link --------------------------------------------------


async def test_a_link_is_sent_for_a_known_address(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    await resets.request(EMAIL)

    assert len(sender.sent) == 1
    assert sender.sent[0][0].id == account.id
    assert sender.sent[0][2] == "email"
    assert sender.last_link.startswith(f"{FRONTEND}/reset-password?token=")


async def test_a_phone_number_works_as_the_identifier(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    """Someone who registered by phone should not have to remember an address."""
    await resets.request("01788000001")

    assert sender.sent[0][2] == "phone"


async def test_an_unknown_address_sends_nothing_and_says_nothing(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    """The whole point: no exception, no signal, nothing to enumerate with."""
    await resets.request("nobody@bwin.example.com")

    assert sender.sent == []


async def test_a_suspended_account_is_sent_nothing(
    resets: PasswordResetService, session: AsyncSession, sender: RecordingSender
) -> None:
    """A link would be a dead end that confirms the account is real."""
    await make_user(
        session,
        email="blocked@bwin.example.com",
        phone=None,
        status=UserStatus.SUSPENDED,
    )

    await resets.request("blocked@bwin.example.com")

    assert sender.sent == []


async def test_a_social_only_account_can_still_set_a_first_password(
    resets: PasswordResetService, session: AsyncSession, sender: RecordingSender
) -> None:
    """No password to recover, but recovery is how you get one."""
    user = await make_user(
        session, email="social@bwin.example.com", phone=None, password=None
    )
    assert user.has_password is False

    await resets.request("social@bwin.example.com")
    await resets.reset(sender.last_token, NEW_PASSWORD)

    refreshed = await UserService(session).get(user.id)
    assert refreshed.has_password is True


async def test_the_stored_row_does_not_hold_the_token(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    """A database dump must not give up working reset links."""
    await resets.request(EMAIL)
    stored = await resets.tokens.latest_for_user(account.id)

    assert stored is not None
    assert stored.token_hash != sender.last_token
    assert stored.token_hash == token_fingerprint(sender.last_token)


async def test_the_request_records_where_it_came_from(
    resets: PasswordResetService, account: User
) -> None:
    """So "who tried to reset my password?" has an answer."""
    await resets.request(EMAIL, SessionContext(ip_address="203.0.113.7"))
    stored = await resets.tokens.latest_for_user(account.id)

    assert stored is not None
    assert stored.requested_ip == "203.0.113.7"


# -- Throttling ---------------------------------------------------------


async def test_a_second_request_is_refused_during_the_cooldown(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    """Otherwise this endpoint is a way to flood somebody else's inbox."""
    await resets.request(EMAIL)
    await resets.request(EMAIL)

    assert len(sender.sent) == 1


async def test_the_hourly_cap_holds(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    """Spacing the requests out gets past the cooldown, not past the cap."""
    for _ in range(PASSWORD_RESET_MAX_PER_HOUR + 2):
        await resets.request(EMAIL)
        # Step back past the cooldown without waiting for it.
        latest = await resets.tokens.latest_for_user(account.id)
        if latest is not None:
            latest.created_at = latest.created_at - timedelta(minutes=5)
            await session.commit()

    assert len(sender.sent) == PASSWORD_RESET_MAX_PER_HOUR


async def test_throttling_looks_the_same_from_outside(
    resets: PasswordResetService, account: User
) -> None:
    """It has to: a visible throttle is itself an answer about the account."""
    await resets.request(EMAIL)

    # No exception, no return value - identical to a successful request.
    assert await resets.request(EMAIL) is None


# -- Using a link -------------------------------------------------------


async def test_a_reset_changes_the_password(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    await resets.request(EMAIL)

    updated = await resets.reset(sender.last_token, NEW_PASSWORD)

    assert verify_password(NEW_PASSWORD, updated.password_hash) is True
    assert verify_password(OLD_PASSWORD, updated.password_hash) is False


async def test_the_new_password_signs_in(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    await resets.request(EMAIL)
    await resets.reset(sender.last_token, NEW_PASSWORD)

    signed_in = await AuthService(session).login(
        LoginRequest(identifier=EMAIL, password=NEW_PASSWORD)
    )

    assert signed_in.user.id == account.id


async def test_a_link_works_exactly_once(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    await resets.request(EMAIL)
    token = sender.last_token
    await resets.reset(token, NEW_PASSWORD)

    with pytest.raises(BadRequestException):
        await resets.reset(token, "Another#Password2026")


async def test_asking_again_retires_the_earlier_link(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    """Or an attacker who triggered a reset keeps a working token."""
    await resets.request(EMAIL)
    first = sender.last_token

    latest = await resets.tokens.latest_for_user(account.id)
    assert latest is not None
    latest.created_at = latest.created_at - timedelta(minutes=5)
    await session.commit()

    await resets.request(EMAIL)

    with pytest.raises(BadRequestException):
        await resets.reset(first, NEW_PASSWORD)

    # The newest one still works.
    assert await resets.reset(sender.last_token, NEW_PASSWORD)


async def test_an_expired_link_is_refused(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    await resets.request(EMAIL)
    stored = await resets.tokens.latest_for_user(account.id)
    assert stored is not None

    stored.expires_at = stored.created_at - timedelta(seconds=1)
    await session.commit()

    with pytest.raises(BadRequestException):
        await resets.reset(sender.last_token, NEW_PASSWORD)


async def test_an_invented_token_is_refused(
    resets: PasswordResetService, account: User
) -> None:
    with pytest.raises(BadRequestException):
        await resets.reset("not-a-real-token", NEW_PASSWORD)


async def test_a_reset_ends_every_session(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    """A reset usually follows a compromise; whoever prompted it loses access."""
    auth = AuthService(session)
    for _ in range(2):
        await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    assert len(await auth.list_sessions(account.id)) == 2

    await resets.request(EMAIL)
    await resets.reset(sender.last_token, NEW_PASSWORD)

    assert await auth.list_sessions(account.id) == []


async def test_the_ended_sessions_say_why(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    auth = AuthService(session)
    await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    await resets.request(EMAIL)
    await resets.reset(sender.last_token, NEW_PASSWORD)

    history = await auth.list_sessions(account.id, active_only=False)

    assert history[0].revoked_reason == RevocationReason.PASSWORD_CHANGED


async def test_a_reset_kills_the_access_tokens_too(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    """Revoking refresh tokens alone leaves an access token working.

    Which would give whoever prompted the reset up to another half hour of
    access - exactly what the reset was meant to take away from them.
    """
    auth = AuthService(session)
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    await resets.request(EMAIL)
    await resets.reset(sender.last_token, NEW_PASSWORD)

    with pytest.raises(UnauthorizedException):
        await auth.authenticate(signed_in.tokens.access_token)


async def test_tokens_issued_after_the_reset_still_work(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    """The cutoff must not be so blunt that signing in again fails too."""
    await resets.request(EMAIL)
    await resets.reset(sender.last_token, NEW_PASSWORD)

    auth = AuthService(session)
    signed_in = await auth.login(LoginRequest(identifier=EMAIL, password=NEW_PASSWORD))

    assert (await auth.authenticate(signed_in.tokens.access_token)).id == account.id


async def test_resetting_by_email_verifies_the_address(
    resets: PasswordResetService, session: AsyncSession, sender: RecordingSender
) -> None:
    """Receiving the link proves control of the address, which is the test."""
    user = await make_user(
        session,
        email="unverified@bwin.example.com",
        phone=None,
        status=UserStatus.PENDING,
    )
    assert user.email_verified is False

    await resets.request("unverified@bwin.example.com")
    await resets.reset(sender.last_token, NEW_PASSWORD)

    refreshed = await UserService(session).get(user.id)
    assert refreshed.email_verified is True
    # A verified contact means the account is no longer merely pending.
    assert refreshed.status == UserStatus.ACTIVE


async def test_a_suspension_during_the_flow_stops_the_reset(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    await resets.request(EMAIL)

    account.status = UserStatus.SUSPENDED
    await session.commit()

    with pytest.raises(BadRequestException):
        await resets.reset(sender.last_token, NEW_PASSWORD)


# -- Checking a link ----------------------------------------------------


async def test_a_valid_link_checks_out(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    await resets.request(EMAIL)

    status_ = await resets.check(sender.last_token)

    assert status_.valid is True


async def test_the_checked_identifier_is_masked(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    """Enough to recognise your own account, not enough to learn whose it is."""
    await resets.request(EMAIL)

    masked = (await resets.check(sender.last_token)).masked_identifier

    assert masked is not None
    assert masked.startswith("lo")
    assert masked.endswith("@bwin.example.com")
    assert "locked.out" not in masked


async def test_a_spent_link_does_not_check_out(
    resets: PasswordResetService, account: User, sender: RecordingSender
) -> None:
    await resets.request(EMAIL)
    token = sender.last_token
    await resets.reset(token, NEW_PASSWORD)

    assert (await resets.check(token)).valid is False


async def test_checking_an_invented_token_reveals_nothing(
    resets: PasswordResetService, account: User
) -> None:
    status_ = await resets.check("made-up")

    assert status_.valid is False
    assert status_.masked_identifier is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("student@bwin.example.com", "st•••••@bwin.example.com"),
        # 14 characters, the last two kept.
        ("+8801788000001", "••••••••••••01"),
        (None, None),
    ],
)
def test_masking(raw: str | None, expected: str | None) -> None:
    masked = PasswordResetService._mask(raw)

    assert masked == expected
    # Whatever the input, the length is not a clue to the original either way.
    if raw is not None:
        assert masked is not None and len(masked) == len(raw)


# -- Changing your own password -----------------------------------------


async def test_changing_a_password_needs_the_current_one(
    resets: PasswordResetService, account: User
) -> None:
    """So a hijacked session cannot lock the owner out."""
    with pytest.raises(ForbiddenException):
        await resets.change_password(
            account, current_password="wrong", new_password=NEW_PASSWORD
        )


async def test_changing_a_password_ends_other_sessions(
    resets: PasswordResetService, account: User, session: AsyncSession
) -> None:
    auth = AuthService(session)
    await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    ended, replacement = await resets.change_password(
        account, current_password=OLD_PASSWORD, new_password=NEW_PASSWORD
    )

    assert ended == 1
    assert replacement is not None
    # The one session left is the replacement.
    assert len(await auth.list_sessions(account.id)) == 1


async def test_the_replacement_token_works_and_the_old_one_does_not(
    resets: PasswordResetService, account: User, session: AsyncSession
) -> None:
    """A change retires every token, so the caller is handed a fresh pair."""
    auth = AuthService(session)
    before = await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    _, replacement = await resets.change_password(
        account, current_password=OLD_PASSWORD, new_password=NEW_PASSWORD
    )

    assert replacement is not None
    assert (await auth.authenticate(replacement.access_token)).id == account.id

    with pytest.raises(UnauthorizedException):
        await auth.authenticate(before.tokens.access_token)


async def test_other_sessions_can_be_kept(
    resets: PasswordResetService, account: User, session: AsyncSession
) -> None:
    """Opting out leaves the existing tokens alone, so none are replaced."""
    auth = AuthService(session)
    before = await auth.login(LoginRequest(identifier=EMAIL, password=OLD_PASSWORD))

    ended, replacement = await resets.change_password(
        account,
        current_password=OLD_PASSWORD,
        new_password=NEW_PASSWORD,
        sign_out_other_sessions=False,
    )

    assert ended == 0
    assert replacement is None
    assert len(await auth.list_sessions(account.id)) == 1
    assert await auth.authenticate(before.tokens.access_token)


# -- Maintenance --------------------------------------------------------


async def test_old_links_can_be_purged(
    resets: PasswordResetService,
    account: User,
    sender: RecordingSender,
    session: AsyncSession,
) -> None:
    await resets.request(EMAIL)
    stored = await resets.tokens.latest_for_user(account.id)
    assert stored is not None

    stored.expires_at = stored.created_at - timedelta(days=90)
    await session.commit()

    assert await resets.purge_expired() == 1
    assert await resets.tokens.latest_for_user(account.id) is None


async def test_purging_leaves_live_links_alone(
    resets: PasswordResetService, account: User
) -> None:
    await resets.request(EMAIL)

    assert await resets.purge_expired() == 0
    assert await resets.tokens.latest_for_user(account.id) is not None


# -- Through the API ----------------------------------------------------


@pytest.fixture
def api(client: TestClient, account: User) -> TestClient:
    return client


def test_forgot_password_answers_the_same_either_way(api: TestClient) -> None:
    """The response has to be identical, body and status alike."""
    known = api.post("/api/v1/auth/forgot-password", json={"identifier": EMAIL})
    unknown = api.post(
        "/api/v1/auth/forgot-password",
        json={"identifier": "ghost@bwin.example.com"},
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.json()["message"] == RESET_REQUESTED_MESSAGE


def test_forgot_password_never_returns_a_token(api: TestClient) -> None:
    """The link goes to the inbox; putting it in the response defeats that."""
    response = api.post("/api/v1/auth/forgot-password", json={"identifier": EMAIL})

    assert response.json()["data"] is None
    assert "token" not in response.text


def test_an_invalid_reset_token_is_refused(api: TestClient) -> None:
    response = api.post(
        "/api/v1/auth/reset-password",
        json={"token": "made-up", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


def test_a_short_password_is_rejected_before_the_token_is_spent(
    api: TestClient,
) -> None:
    response = api.post(
        "/api/v1/auth/reset-password", json={"token": "anything", "new_password": "x"}
    )

    assert response.status_code == 422


def test_verifying_a_bad_token_is_a_200_saying_no(api: TestClient) -> None:
    """A page asking "is this link good?" wants an answer, not an error."""
    response = api.post("/api/v1/auth/reset-password/verify", json={"token": "made-up"})

    assert response.status_code == 200
    assert response.json()["data"]["valid"] is False


def test_change_password_requires_a_token(api: TestClient) -> None:
    response = api.post(
        "/api/v1/auth/change-password",
        json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


def test_the_endpoints_are_all_present(api: TestClient) -> None:
    paths = api.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/forgot-password" in paths
    assert "/api/v1/auth/reset-password" in paths
    assert "/api/v1/auth/reset-password/verify" in paths
    assert "/api/v1/auth/change-password" in paths
