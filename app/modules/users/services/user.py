"""Business logic for users."""

import logging
import uuid

from fastapi import UploadFile
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
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.media.constants import AVATAR_SUBDIRECTORY
from app.modules.media.services import ImageUploadService
from app.modules.media.storage.base import StorageBackend
from app.modules.roles.constants import SystemRole
from app.modules.roles.repositories.role import RoleRepository
from app.modules.settings.constants import SettingKey
from app.modules.settings.services.setting import SettingService
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
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)

#: Only used if the `app_base_url` setting row is somehow missing (it ships
#: seeded - see app/modules/settings/constants.py:SYSTEM_SETTINGS) - avatar
#: uploads should still work on a fresh, unseeded database rather than fail.
DEFAULT_APP_BASE_URL = "http://127.0.0.1:8000"


class UserService:
    """Coordinates user reads, writes, role assignment and social linking."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.USERS)
        self.roles = RoleRepository(session)
        self.settings = SettingService(session)

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

        await self.activity.record(
            ActivityAction.CREATE,
            entity=user,
            description=f"Created user {user.email or user.phone}",
            # `snapshot` drops `password_hash` on the way past: the field name
            # matches a sensitive fragment, so it is replaced rather than
            # stored, here and everywhere else a user is logged.
            new_values=snapshot(user),
        )
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

        before = snapshot(user, fields=changes.keys())
        updated = await self.repository.update(user, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=(
                    f"Updated {', '.join(sorted(new_values))} "
                    f"on user {updated.email or updated.phone}"
                ),
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def set_avatar(
        self, user_id: uuid.UUID, upload: UploadFile, storage: StorageBackend
    ) -> User:
        """Upload a profile picture and point `avatar_url` at it.

        The new file is stored before anything is written to the row, so a
        rejected or failed upload never touches the user. The previous image
        is removed only after that row update lands, and only on a
        best-effort basis - a stale orphaned file is a much smaller problem
        than a user record briefly pointing at nothing.
        """
        user = await self.repository.get_or_raise(user_id)
        uploader = ImageUploadService(storage)
        base_url = await self._app_base_url()

        new_url = await uploader.upload(
            upload, subdirectory=AVATAR_SUBDIRECTORY, base_url=base_url
        )
        old_url = user.avatar_url

        updated = await self.repository.update(user, avatar_url=new_url)

        await self.activity.record(
            ActivityAction.UPDATE,
            entity=updated,
            description=f"Updated the avatar for {updated.full_name}",
            old_values={"avatar_url": old_url},
            new_values={"avatar_url": new_url},
        )
        await self.session.commit()

        if old_url:
            await uploader.delete(old_url, base_url=base_url)

        return updated

    async def clear_avatar(self, user_id: uuid.UUID, storage: StorageBackend) -> User:
        user = await self.repository.get_or_raise(user_id)
        if user.avatar_url is None:
            return user

        old_url = user.avatar_url
        updated = await self.repository.update(user, avatar_url=None)

        await self.activity.record(
            ActivityAction.UPDATE,
            entity=updated,
            description=f"Removed the avatar for {updated.full_name}",
            old_values={"avatar_url": old_url},
            new_values={"avatar_url": None},
        )
        await self.session.commit()

        await ImageUploadService(storage).delete(
            old_url, base_url=await self._app_base_url()
        )

        return updated

    async def _app_base_url(self) -> str:
        """This application's own public origin - see `SettingKey.APP_BASE_URL`.

        The single source of truth for "what is this API's address", already
        relied on to build OAuth callback URLs - avatar URLs read the same
        row rather than a second, independently-configured value that could
        drift from it.
        """
        return await self.settings.value(
            SettingKey.APP_BASE_URL.value, default=DEFAULT_APP_BASE_URL
        )

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

        # Read before the write: `update` mutates this same instance, so
        # afterwards there is no "before" left to record.
        had_password = user.has_password

        updated = await self.repository.update(
            user, password_hash=hash_password(payload.new_password)
        )

        await self.activity.record(
            ActivityAction.PASSWORD_CHANGE,
            entity=updated,
            description=f"Set a new password for {updated.full_name}",
            # Deliberately no values: that the password changed is the fact
            # worth keeping, and neither side of it may be written down.
            new_values={"had_password_before": had_password},
        )
        await self.session.commit()

        logger.info("Password changed for user %s", user.id)
        return updated

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.repository.get_or_raise(user_id)
        before = snapshot(user)
        await self.repository.soft_delete(user)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=user,
            description=f"Deleted user {user.email or user.phone}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_or_raise(user_id, include_deleted=True)
        restored = await self.repository.restore(user)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored user {restored.email or restored.phone}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    async def record_login(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_or_raise(user_id)
        updated = await self.repository.update(user, last_login_at=utc_now())

        await self.activity.record(
            ActivityAction.LOGIN,
            entity=updated,
            description=f"Recorded a sign-in for {updated.full_name}",
            actor=updated,
        )
        await self.session.commit()
        return updated

    async def verify_email(self, user_id: uuid.UUID) -> User:
        return await self._mark_verified(user_id, "email_verified_at")

    async def verify_phone(self, user_id: uuid.UUID) -> User:
        return await self._mark_verified(user_id, "phone_verified_at")

    async def _mark_verified(self, user_id: uuid.UUID, field: str) -> User:
        user = await self.repository.get_or_raise(user_id)
        previous_status = user.status
        changes: dict[str, object] = {field: utc_now()}

        # A verified contact means the account is no longer merely pending.
        if user.status == UserStatus.PENDING:
            changes["status"] = UserStatus.ACTIVE.value

        updated = await self.repository.update(user, **changes)

        await self.activity.record(
            ActivityAction.VERIFY,
            entity=updated,
            description=(
                f"Verified the {field.removesuffix('_verified_at')} of "
                f"{updated.full_name}"
            ),
            old_values={"status": previous_status},
            new_values={"status": updated.status, "verified": field},
        )
        await self.session.commit()
        return updated

    # -- Roles ----------------------------------------------------------

    async def assign_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> User:
        user = await self.repository.get_or_raise(user_id)
        held = sorted(user.role_slugs)

        await self._assign_validated_roles(user.id, role_ids)
        await self.session.commit()
        await self.session.refresh(user)

        await self._record_role_change(
            ActivityAction.ROLE_ASSIGN, user, held, "Granted"
        )
        return user

    async def revoke_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> User:
        user = await self.repository.get_or_raise(user_id)
        held = sorted(user.role_slugs)

        await self.repository.revoke_roles(user.id, role_ids)
        await self.session.commit()
        await self.session.refresh(user)

        await self._record_role_change(
            ActivityAction.ROLE_REVOKE, user, held, "Revoked"
        )
        return user

    async def replace_roles(
        self, user_id: uuid.UUID, role_ids: list[uuid.UUID]
    ) -> User:
        user = await self.repository.get_or_raise(user_id)
        held = sorted(user.role_slugs)

        await self.repository.revoke_all_roles(user.id)
        await self._assign_validated_roles(user.id, role_ids)
        await self.session.commit()
        await self.session.refresh(user)

        await self._record_role_change(
            ActivityAction.ROLE_ASSIGN, user, held, "Replaced the roles of"
        )
        return user

    async def _record_role_change(
        self, action: ActivityAction, user: User, held: list[str], verb: str
    ) -> None:
        """Record what an account may now do, and what it could before.

        Written after the commit and refresh rather than before, because the
        entry has to name the roles the account ended up with - and that is
        only known once the association rows have been written and reloaded.
        A change in authority is the entry an auditor looks for first, so it
        records the whole set on both sides rather than the delta.
        """
        now_held = sorted(user.role_slugs)

        if now_held == held:
            return

        await self.activity.record(
            action,
            entity=user,
            description=(
                f"{verb} roles on {user.email or user.phone}: "
                f"{', '.join(now_held) or 'none'}"
            ),
            old_values={"roles": held},
            new_values={"roles": now_held},
        )
        await self.session.commit()

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

        await self.activity.record(
            ActivityAction.ACCOUNT_LINK,
            entity=user,
            description=(
                f"Linked a {payload.provider.value} account to "
                f"{user.email or user.phone}"
            ),
            new_values={
                "provider": payload.provider.value,
                "provider_email": payload.email,
            },
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

        await self.activity.record(
            ActivityAction.ACCOUNT_UNLINK,
            entity=user,
            description=(
                f"Unlinked the {provider} account from {user.email or user.phone}"
            ),
            old_values={"provider": provider},
        )
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

                await self.activity.record(
                    ActivityAction.ACCOUNT_LINK,
                    entity=by_email,
                    description=(
                        f"Linked a {payload.provider.value} account to "
                        f"{by_email.email} on a verified address match"
                    ),
                    actor=by_email,
                    new_values={
                        "provider": payload.provider.value,
                        "matched_on": "verified_email",
                    },
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

        await self.activity.record(
            ActivityAction.CREATE,
            entity=user,
            description=(
                f"Created user {user.email} from a {payload.provider.value} sign-in"
            ),
            # The account creating itself: nobody was signed in when this
            # request arrived, so the new account is named as the actor
            # rather than leaving the entry anonymous.
            actor=user,
            new_values=snapshot(user) | {"provider": payload.provider.value},
        )
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
