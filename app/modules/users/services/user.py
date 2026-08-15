"""Business logic for users."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.security import hash_password, verify_password
from app.modules.roles.constants import SystemRole
from app.modules.roles.repositories.role import RoleRepository
from app.modules.users.constants import SOCIAL_PROVIDERS, UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.repositories.user import UserRepository
from app.modules.users.schemas.user import (
    PasswordSet,
    SocialLogin,
    UserCreate,
    UserUpdate,
)
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)


class UserService:
    """Coordinates user reads, writes, role assignment and social linking."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.roles = RoleRepository(session)

    # -- Reads ----------------------------------------------------------

    async def get(self, user_id: uuid.UUID) -> User:
        return await self.repository.get_or_raise(user_id)

    async def get_by_identifier(self, identifier: str) -> User:
        """Look a user up by email or phone, whichever they supplied."""
        user = await self.repository.get_by_identifier(identifier)
        if user is None:
            raise NotFoundException("User")
        return user

    async def list_users(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: UserStatus | None = None,
        role_slug: str | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[User], int]:
        filters = []
        if status:
            filters.append(Filter.eq("status", status.value))

        if role_slug:
            role = await self.roles.get_by_slug(role_slug)
            if role is None:
                raise BadRequestException(f"Unknown role '{role_slug}'.")
            filters.append(Filter.in_("id", await self._user_ids_for_role(role.id)))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["email", "phone", "first_name", "last_name"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def _user_ids_for_role(self, role_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == role_id)
        )
        return list(result.scalars().all())

    # -- Writes ---------------------------------------------------------

    async def create(self, payload: UserCreate) -> User:
        await self._guard_identifiers(payload.email, payload.phone)

        user = await self.repository.create(
            email=payload.email,
            phone=payload.phone,
            password_hash=hash_password(payload.password) if payload.password else None,
            first_name=payload.first_name,
            last_name=payload.last_name,
            avatar_url=payload.avatar_url,
            bio=payload.bio,
            language=payload.language.value,
            status=payload.status.value,
        )

        role_ids = payload.role_ids or [await self._default_role_id()]
        await self._assign_validated_roles(user.id, role_ids)

        await self.session.commit()
        await self.session.refresh(user)

        logger.info("Created user %s", user.id)
        return user

    async def update(self, user_id: uuid.UUID, payload: UserUpdate) -> User:
        user = await self.repository.get_or_raise(user_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return user

        await self._guard_identifiers(
            changes.get("email"), changes.get("phone"), exclude_id=user.id
        )

        # Neither identifier may be cleared if it would leave the account
        # with no way to sign in - the database CHECK would reject it anyway,
        # but as an opaque IntegrityError rather than a useful message.
        resulting_email = changes.get("email", user.email)
        resulting_phone = changes.get("phone", user.phone)
        if not resulting_email and not resulting_phone:
            raise BadRequestException(
                "A user must keep either an email address or a phone number."
            )

        if "language" in changes and changes["language"] is not None:
            changes["language"] = changes["language"].value
        if "status" in changes and changes["status"] is not None:
            changes["status"] = changes["status"].value

        updated = await self.repository.update(user, **changes)
        await self.session.commit()
        return updated

    async def set_password(self, user_id: uuid.UUID, payload: PasswordSet) -> User:
        """Set or replace a password.

        An account that already has one must prove it, so a hijacked session
        cannot lock the owner out. An account created through Google has none
        yet and can set one straight away.
        """
        user = await self.repository.get_or_raise(user_id)

        if user.has_password:
            if not payload.current_password:
                raise BadRequestException("The current password is required.")
            if not verify_password(payload.current_password, user.password_hash):
                raise ForbiddenException("The current password is incorrect.")

        updated = await self.repository.update(
            user, password_hash=hash_password(payload.new_password)
        )
        await self.session.commit()

        logger.info("Password changed for user %s", user.id)
        return updated

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.repository.get_or_raise(user_id)
        await self.repository.soft_delete(user)
        await self.session.commit()

    async def restore(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_or_raise(user_id, include_deleted=True)
        restored = await self.repository.restore(user)
        await self.session.commit()
        return restored

    async def record_login(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_or_raise(user_id)
        updated = await self.repository.update(user, last_login_at=utc_now())
        await self.session.commit()
        return updated

    async def verify_email(self, user_id: uuid.UUID) -> User:
        return await self._mark_verified(user_id, "email_verified_at")

    async def verify_phone(self, user_id: uuid.UUID) -> User:
        return await self._mark_verified(user_id, "phone_verified_at")

    async def _mark_verified(self, user_id: uuid.UUID, field: str) -> User:
        user = await self.repository.get_or_raise(user_id)
        changes: dict[str, object] = {field: utc_now()}

        # A verified contact means the account is no longer merely pending.
        if user.status == UserStatus.PENDING:
            changes["status"] = UserStatus.ACTIVE.value

        updated = await self.repository.update(user, **changes)
        await self.session.commit()
        return updated

    # -- Roles ----------------------------------------------------------

    async def assign_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> User:
        user = await self.repository.get_or_raise(user_id)
        await self._assign_validated_roles(user.id, role_ids)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def revoke_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> User:
        user = await self.repository.get_or_raise(user_id)
        await self.repository.revoke_roles(user.id, role_ids)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def replace_roles(
        self, user_id: uuid.UUID, role_ids: list[uuid.UUID]
    ) -> User:
        user = await self.repository.get_or_raise(user_id)

        await self.repository.revoke_all_roles(user.id)
        await self._assign_validated_roles(user.id, role_ids)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def _assign_validated_roles(
        self, user_id: uuid.UUID, role_ids: list[uuid.UUID]
    ) -> None:
        """Reject unknown role ids rather than silently granting nothing."""
        for role_id in role_ids:
            if await self.roles.get(role_id) is None:
                raise BadRequestException(f"Unknown role '{role_id}'.")

        await self.repository.assign_roles(user_id, role_ids)

    async def _default_role_id(self) -> uuid.UUID:
        """New accounts start as students unless told otherwise."""
        role = await self.roles.get_by_slug(SystemRole.STUDENT)
        if role is None:
            raise BadRequestException(
                "The default 'student' role is missing. Run the migrations."
            )
        return role.id

    # -- Social identities ----------------------------------------------

    async def link_social_account(
        self, user_id: uuid.UUID, payload: SocialLogin
    ) -> UserIdentity:
        """Attach a Google or Facebook account to an existing user."""
        user = await self.repository.get_or_raise(user_id)

        owner = await self.repository.get_by_provider(
            payload.provider.value, payload.provider_user_id
        )
        if owner is not None:
            if owner.id == user.id:
                raise ConflictException(
                    f"This {payload.provider.value} account is already linked."
                )
            raise ConflictException(
                f"That {payload.provider.value} account belongs to another user."
            )

        if await self.repository.get_identity(user.id, payload.provider.value):
            raise ConflictException(
                f"This user already has a {payload.provider.value} account linked."
            )

        identity = await self.repository.add_identity(
            user.id,
            payload.provider.value,
            payload.provider_user_id,
            payload.email,
        )
        await self.session.commit()

        # The session keeps objects alive across commits (expire_on_commit is
        # off), so the user's already-loaded `identities` would still show the
        # collection as it was before this link.
        await self.session.refresh(user, attribute_names=["identities"])

        logger.info("Linked %s to user %s", payload.provider.value, user.id)
        return identity

    async def unlink_social_account(self, user_id: uuid.UUID, provider: str) -> None:
        """Remove a social login, refusing to strip the last way in."""
        user = await self.repository.get_or_raise(user_id)

        if provider not in user.linked_providers():
            raise NotFoundException(f"No {provider} account linked to this user")

        if not user.has_password and len(user.identities) == 1:
            raise BadRequestException(
                "This is the only way to sign in to this account. "
                "Set a password before unlinking it."
            )

        await self.repository.remove_identity(user.id, provider)
        await self.session.commit()
        await self.session.refresh(user, attribute_names=["identities"])

    async def resolve_social_login(self, payload: SocialLogin) -> tuple[User, bool]:
        """Find or create the user behind a verified social identity.

        Returns the user and whether the account was newly created. The
        provider is trusted here: verifying the token with Google or Facebook
        happens before this is called.
        """
        if payload.provider not in SOCIAL_PROVIDERS:
            raise BadRequestException(f"'{payload.provider}' is not a social provider.")

        existing = await self.repository.get_by_provider(
            payload.provider.value, payload.provider_user_id
        )
        if existing is not None:
            return existing, False

        if payload.email:
            by_email = await self.repository.get_by_email(payload.email)
            if by_email is not None:
                if not payload.email_verified:
                    # Linking on an unverified address is account takeover:
                    # anyone can put someone else's address on a profile and
                    # then sign in as them. Refuse, and point at the safe
                    # route - sign in normally, then link from settings.
                    raise ForbiddenException(
                        f"{payload.provider.value.title()} has not verified "
                        f"'{payload.email}', and an account already uses it. "
                        "Sign in with your password first, then link the "
                        "account from your profile."
                    )

                # The provider vouched for the address, so this is the same
                # person - link rather than create a duplicate account.
                await self.repository.add_identity(
                    by_email.id,
                    payload.provider.value,
                    payload.provider_user_id,
                    payload.email,
                )
                await self.session.commit()
                await self.session.refresh(by_email)
                return by_email, False

        if not payload.email:
            raise BadRequestException(
                f"{payload.provider.value} did not supply an email address, "
                "so a new account cannot be created from it."
            )

        user = await self.repository.create(
            email=payload.email,
            first_name=payload.first_name or payload.email.split("@")[0],
            last_name=payload.last_name,
            avatar_url=payload.avatar_url,
            # No password was set and none is needed, so the account is
            # active rather than pending. The address is marked verified only
            # if the provider actually says so.
            status=UserStatus.ACTIVE.value,
            email_verified_at=utc_now() if payload.email_verified else None,
        )

        await self.repository.add_identity(
            user.id, payload.provider.value, payload.provider_user_id, payload.email
        )
        await self._assign_validated_roles(user.id, [await self._default_role_id()])

        await self.session.commit()
        await self.session.refresh(user)

        logger.info("Created user %s from %s", user.id, payload.provider.value)
        return user, True

    # -- Helpers --------------------------------------------------------

    async def _guard_identifiers(
        self,
        email: str | None,
        phone: str | None,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        if email and await self.repository.email_exists(email, exclude_id=exclude_id):
            raise ConflictException(f"'{email}' is already registered.")

        if phone and await self.repository.phone_exists(phone, exclude_id=exclude_id):
            raise ConflictException(f"'{phone}' is already registered.")
