"""Tests for the users module."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.security import (
    BCRYPT_MAX_BYTES,
    PasswordTooLongError,
    hash_password,
    verify_password,
)
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import (
    AuthProvider,
    UserStatus,
    identifier_type,
    normalize_email,
    normalize_phone,
)
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import (
    PasswordSet,
    SocialLogin,
    UserCreate,
    UserUpdate,
)
from app.modules.users.services.user import UserService


@pytest.fixture
async def users(session: AsyncSession) -> AsyncIterator[UserService]:
    """A clean slate of users, roles and permissions, restored afterwards."""

    async def wipe() -> None:
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

    yield UserService(session)

    await wipe()


# -- Password hashing ---------------------------------------------------


def test_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_hashing_is_salted() -> None:
    """Two identical passwords must not produce the same hash."""
    assert hash_password("same-password") != hash_password("same-password")


def test_verifying_against_no_password_is_false() -> None:
    """A social-only account fails the check rather than crashing."""
    assert verify_password("anything", None) is False


def test_overlong_passwords_are_refused_not_truncated() -> None:
    """Truncation would let two different passwords open one account."""
    with pytest.raises(PasswordTooLongError):
        hash_password("a" * (BCRYPT_MAX_BYTES + 1))


# -- Identifier handling ------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("01712345678", "+8801712345678"),
        ("+8801712345678", "+8801712345678"),
        ("008801712345678", "+8801712345678"),
        ("01712-345678", "+8801712345678"),
        ("017 1234 5678", "+8801712345678"),
        ("8801712345678", "+8801712345678"),
    ],
)
def test_phone_normalizes_to_e164(value: str, expected: str) -> None:
    """However it is typed, the same number must match the same account."""
    assert normalize_phone(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "123", "+", "1" * 20, "abc"])
def test_invalid_phones_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="Phone|digits"):
        normalize_phone(value)


def test_email_is_normalized() -> None:
    assert normalize_email("  Ali@Example.COM ") == "ali@example.com"


def test_identifier_type_detection() -> None:
    assert identifier_type("ali@example.com") == "email"
    assert identifier_type("+8801712345678") == "phone"


# -- Creation -----------------------------------------------------------


async def test_create_with_email_only(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    assert user.email == "ali@example.com"
    assert user.phone is None
    assert user.has_password is False


async def test_create_with_phone_only(users: UserService) -> None:
    user = await users.create(UserCreate(phone="01712345678", first_name="Ali"))

    assert user.phone == "+8801712345678"
    assert user.email is None


async def test_create_with_both_identifiers(users: UserService) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", phone="01712345678", first_name="Ali")
    )

    assert user.email == "ali@example.com"
    assert user.phone == "+8801712345678"


def test_create_requires_an_identifier() -> None:
    with pytest.raises(ValueError, match="email address or a phone number"):
        UserCreate(first_name="Ali")


async def test_create_hashes_the_password(users: UserService) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="secret123")
    )

    assert user.password_hash is not None
    assert user.password_hash != "secret123"
    assert verify_password("secret123", user.password_hash) is True


async def test_new_users_become_students_by_default(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    assert user.role_slugs == {"student"}


async def test_create_with_explicit_roles(
    users: UserService, session: AsyncSession
) -> None:
    instructor = await RoleService(session).get_by_slug("instructor")

    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", role_ids=[instructor.id])
    )

    assert user.role_slugs == {"instructor"}


async def test_duplicate_email_is_rejected(users: UserService) -> None:
    await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    with pytest.raises(ConflictException, match="already registered"):
        await users.create(UserCreate(email="ali@example.com", first_name="Other"))


async def test_duplicate_email_check_ignores_casing(users: UserService) -> None:
    await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    with pytest.raises(ConflictException):
        await users.create(UserCreate(email="ALI@EXAMPLE.COM", first_name="Other"))


async def test_duplicate_phone_is_rejected_across_formats(
    users: UserService,
) -> None:
    """`01712345678` and `+8801712345678` are the same number."""
    await users.create(UserCreate(phone="01712345678", first_name="Ali"))

    with pytest.raises(ConflictException, match="already registered"):
        await users.create(UserCreate(phone="+8801712345678", first_name="Other"))


async def test_unknown_role_is_rejected(users: UserService) -> None:
    with pytest.raises(BadRequestException, match="Unknown role"):
        await users.create(
            UserCreate(
                email="ali@example.com", first_name="Ali", role_ids=[uuid.uuid4()]
            )
        )


# -- Sign-in lookup -----------------------------------------------------


async def test_lookup_by_email(users: UserService) -> None:
    created = await users.create(
        UserCreate(email="ali@example.com", phone="01712345678", first_name="Ali")
    )

    found = await users.get_by_identifier("ali@example.com")

    assert found.id == created.id


async def test_lookup_by_phone(users: UserService) -> None:
    created = await users.create(
        UserCreate(email="ali@example.com", phone="01712345678", first_name="Ali")
    )

    found = await users.get_by_identifier("+8801712345678")

    assert found.id == created.id


async def test_lookup_by_phone_in_local_format(users: UserService) -> None:
    """A user typing their number the way they always do must still match."""
    created = await users.create(UserCreate(phone="+8801712345678", first_name="Ali"))

    found = await users.get_by_identifier("01712345678")

    assert found.id == created.id


async def test_lookup_by_email_ignores_casing(users: UserService) -> None:
    created = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    found = await users.get_by_identifier("  ALI@Example.com  ")

    assert found.id == created.id


async def test_lookup_of_an_unknown_identifier_raises(users: UserService) -> None:
    with pytest.raises(NotFoundException):
        await users.get_by_identifier("nobody@example.com")


async def test_lookup_of_a_malformed_phone_raises_not_found(
    users: UserService,
) -> None:
    """Garbage must not blow up the sign-in path."""
    with pytest.raises(NotFoundException):
        await users.get_by_identifier("not-a-number")


# -- Update -------------------------------------------------------------


async def test_update_changes_fields(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    updated = await users.update(
        user.id, UserUpdate(first_name="Ali", last_name="Ahsan")
    )

    assert updated.full_name == "Ali Ahsan"


async def test_update_normalizes_a_new_phone(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    updated = await users.update(user.id, UserUpdate(phone="01712345678"))

    assert updated.phone == "+8801712345678"


async def test_update_rejects_an_identifier_owned_by_someone_else(
    users: UserService,
) -> None:
    await users.create(UserCreate(email="taken@example.com", first_name="First"))
    second = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    with pytest.raises(ConflictException):
        await users.update(second.id, UserUpdate(email="taken@example.com"))


async def test_a_user_cannot_be_left_with_no_identifier(users: UserService) -> None:
    """Clearing the only identifier would make the account unreachable."""
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    with pytest.raises(BadRequestException, match="must keep either"):
        await users.update(user.id, UserUpdate(email=None))


async def test_clearing_one_identifier_is_fine_when_another_remains(
    users: UserService,
) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", phone="01712345678", first_name="Ali")
    )

    updated = await users.update(user.id, UserUpdate(email=None))

    assert updated.email is None
    assert updated.phone == "+8801712345678"


# -- Passwords ----------------------------------------------------------


async def test_setting_a_first_password_needs_no_current_one(
    users: UserService,
) -> None:
    """An account created through Google has none to supply."""
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    updated = await users.set_password(user.id, PasswordSet(new_password="secret123"))

    assert verify_password("secret123", updated.password_hash) is True


async def test_changing_a_password_requires_the_current_one(
    users: UserService,
) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="original1")
    )

    with pytest.raises(BadRequestException, match="current password is required"):
        await users.set_password(user.id, PasswordSet(new_password="replacement1"))


async def test_a_wrong_current_password_is_refused(users: UserService) -> None:
    """Otherwise a hijacked session could lock the owner out."""
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="original1")
    )

    with pytest.raises(ForbiddenException, match="incorrect"):
        await users.set_password(
            user.id, PasswordSet(current_password="wrong", new_password="replacement1")
        )


async def test_password_change_succeeds_with_the_right_current_one(
    users: UserService,
) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="original1")
    )

    updated = await users.set_password(
        user.id,
        PasswordSet(current_password="original1", new_password="replacement1"),
    )

    assert verify_password("replacement1", updated.password_hash) is True
    assert verify_password("original1", updated.password_hash) is False


def test_short_passwords_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        PasswordSet(new_password="short")


# -- Roles and permissions ----------------------------------------------


async def test_user_inherits_permissions_from_roles(
    users: UserService, session: AsyncSession
) -> None:
    instructor = await RoleService(session).get_by_slug("instructor")
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", role_ids=[instructor.id])
    )

    assert user.has_permission("course.create") is True
    assert user.has_permission("user.delete") is False


async def test_permissions_combine_across_several_roles(
    users: UserService, session: AsyncSession
) -> None:
    roles = RoleService(session)
    instructor = await roles.get_by_slug("instructor")
    editor = await roles.get_by_slug("editor")

    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))
    user = await users.replace_roles(user.id, [instructor.id, editor.id])

    assert user.has_permission("course.create") is True
    assert user.has_permission("page.update") is True


async def test_highest_level_reflects_the_strongest_role(
    users: UserService, session: AsyncSession
) -> None:
    roles = RoleService(session)
    admin = await roles.get_by_slug("admin")
    student = await roles.get_by_slug("student")

    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))
    user = await users.replace_roles(user.id, [student.id, admin.id])

    assert user.highest_level == 90


async def test_revoking_roles(users: UserService, session: AsyncSession) -> None:
    student = await RoleService(session).get_by_slug("student")
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    user = await users.revoke_roles(user.id, [student.id])

    assert user.role_slugs == set()


# -- Social login -------------------------------------------------------


async def test_social_login_creates_a_new_account(users: UserService) -> None:
    user, created = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
            first_name="Ali",
        )
    )

    assert created is True
    assert user.email == "ali@example.com"
    assert user.linked_providers() == {"google"}


async def test_a_social_account_starts_verified_and_active(
    users: UserService,
) -> None:
    """The provider already proved the address."""
    user, _ = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )

    assert user.status == UserStatus.ACTIVE
    assert user.email_verified is True
    assert user.has_password is False


async def test_returning_social_login_finds_the_same_account(
    users: UserService,
) -> None:
    first, _ = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )

    second, created = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )

    assert created is False
    assert second.id == first.id


async def test_social_login_links_to_an_existing_email_account(
    users: UserService,
) -> None:
    """Otherwise the same person ends up with two accounts."""
    existing = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="secret123")
    )

    user, created = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )

    assert created is False
    assert user.id == existing.id
    assert user.linked_providers() == {"google"}
    assert user.has_password is True


async def test_facebook_and_google_can_both_be_linked(users: UserService) -> None:
    user = await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", password="secret123")
    )

    await users.link_social_account(
        user.id,
        SocialLogin(provider=AuthProvider.GOOGLE, provider_user_id="g-1"),
    )
    await users.link_social_account(
        user.id,
        SocialLogin(provider=AuthProvider.FACEBOOK, provider_user_id="fb-1"),
    )

    refreshed = await users.get(user.id)
    assert refreshed.linked_providers() == {"google", "facebook"}


async def test_a_social_account_cannot_be_linked_to_two_users(
    users: UserService,
) -> None:
    first = await users.create(UserCreate(email="a@example.com", first_name="A"))
    second = await users.create(UserCreate(email="b@example.com", first_name="B"))

    await users.link_social_account(
        first.id, SocialLogin(provider=AuthProvider.GOOGLE, provider_user_id="g-1")
    )

    with pytest.raises(ConflictException, match="belongs to another user"):
        await users.link_social_account(
            second.id,
            SocialLogin(provider=AuthProvider.GOOGLE, provider_user_id="g-1"),
        )


async def test_social_signup_without_an_email_is_refused(
    users: UserService,
) -> None:
    """There would be no identifier to satisfy the account's CHECK constraint."""
    with pytest.raises(BadRequestException, match="did not supply an email"):
        await users.resolve_social_login(
            SocialLogin(provider=AuthProvider.FACEBOOK, provider_user_id="fb-1")
        )


async def test_unlinking_the_only_sign_in_method_is_refused(
    users: UserService,
) -> None:
    user, _ = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )

    with pytest.raises(BadRequestException, match="only way to sign in"):
        await users.unlink_social_account(user.id, "google")


async def test_unlinking_is_allowed_once_a_password_exists(
    users: UserService,
) -> None:
    user, _ = await users.resolve_social_login(
        SocialLogin(
            provider=AuthProvider.GOOGLE,
            provider_user_id="google-123",
            email="ali@example.com",
        )
    )
    await users.set_password(user.id, PasswordSet(new_password="secret123"))

    await users.unlink_social_account(user.id, "google")

    assert (await users.get(user.id)).linked_providers() == set()


# -- Verification and lifecycle -----------------------------------------


async def test_verifying_email_activates_a_pending_account(
    users: UserService,
) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))
    assert user.status == UserStatus.PENDING

    verified = await users.verify_email(user.id)

    assert verified.email_verified is True
    assert verified.status == UserStatus.ACTIVE


async def test_verifying_phone_activates_a_pending_account(
    users: UserService,
) -> None:
    user = await users.create(UserCreate(phone="01712345678", first_name="Ali"))

    verified = await users.verify_phone(user.id)

    assert verified.phone_verified is True
    assert verified.status == UserStatus.ACTIVE


async def test_suspended_accounts_cannot_sign_in(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    suspended = await users.update(user.id, UserUpdate(status=UserStatus.SUSPENDED))

    assert suspended.can_sign_in is False


async def test_delete_and_restore(users: UserService) -> None:
    user = await users.create(UserCreate(email="ali@example.com", first_name="Ali"))

    await users.delete(user.id)
    _, total = await users.list_users(PaginationParams())
    assert total == 0

    await users.restore(user.id)
    _, total = await users.list_users(PaginationParams())
    assert total == 1


# -- Listing ------------------------------------------------------------


async def test_list_filters_by_status(users: UserService) -> None:
    await users.create(UserCreate(email="a@example.com", first_name="A"))
    active = await users.create(UserCreate(email="b@example.com", first_name="B"))
    await users.update(active.id, UserUpdate(status=UserStatus.ACTIVE))

    _, total = await users.list_users(PaginationParams(), status=UserStatus.ACTIVE)

    assert total == 1


async def test_list_filters_by_role(users: UserService, session: AsyncSession) -> None:
    instructor = await RoleService(session).get_by_slug("instructor")
    await users.create(UserCreate(email="a@example.com", first_name="A"))
    await users.create(
        UserCreate(email="b@example.com", first_name="B", role_ids=[instructor.id])
    )

    items, total = await users.list_users(PaginationParams(), role_slug="instructor")

    assert total == 1
    assert items[0].email == "b@example.com"


async def test_list_searches_identifiers_and_names(users: UserService) -> None:
    await users.create(
        UserCreate(email="ali@example.com", first_name="Ali", last_name="Ahsan")
    )
    await users.create(UserCreate(email="other@example.com", first_name="Other"))

    items, _ = await users.list_users(PaginationParams(), search="ahsan")

    assert [item.email for item in items] == ["ali@example.com"]


async def test_list_by_unknown_role_is_rejected(users: UserService) -> None:
    with pytest.raises(BadRequestException, match="Unknown role"):
        await users.list_users(PaginationParams(), role_slug="nope")
