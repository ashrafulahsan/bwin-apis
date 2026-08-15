"""Data access for users, their roles and their linked identities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.users.constants import (
    PROVIDER_ID_COLUMNS,
    IdentifierType,
    identifier_type,
    normalize_email,
    normalize_phone,
)
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.shared.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User
    default_sort_by = "created_at"

    # -- Lookups --------------------------------------------------------

    async def get_by_email(self, email: str) -> User | None:
        return await self.get_by_field("email", normalize_email(email))

    async def get_by_phone(self, phone: str) -> User | None:
        try:
            normalized = normalize_phone(phone)
        except ValueError:
            return None
        return await self.get_by_field("phone", normalized)

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Find a user by whichever of email or phone they signed in with.

        This is what makes "log in with either" work: the caller passes one
        string and does not have to say which kind it is.
        """
        value = identifier.strip()

        if identifier_type(value) is IdentifierType.EMAIL:
            return await self.get_by_email(value)

        return await self.get_by_phone(value)

    async def email_exists(
        self, email: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        return await self._identifier_exists(
            User.email, normalize_email(email), exclude_id
        )

    async def phone_exists(
        self, phone: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        return await self._identifier_exists(
            User.phone, normalize_phone(phone), exclude_id
        )

    async def _identifier_exists(
        self, column: object, value: str, exclude_id: uuid.UUID | None
    ) -> bool:
        """Counts soft-deleted rows, matching the database's unique index."""
        conditions = [column == value]
        if exclude_id is not None:
            conditions.append(User.id != exclude_id)

        result = await self.session.execute(
            select(select(User.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def search_by_identifier(self, term: str) -> list[User]:
        """Match a term against either identifier, for an admin search box."""
        pattern = f"%{term.strip().lower()}%"

        result = await self.session.execute(
            select(User).where(
                or_(User.email.ilike(pattern), User.phone.ilike(pattern))
            )
        )
        return list(result.scalars().all())

    # -- Roles ----------------------------------------------------------

    async def assign_roles(
        self, user_id: uuid.UUID, role_ids: Sequence[uuid.UUID]
    ) -> int:
        if not role_ids:
            return 0

        statement = pg_insert(user_roles).values(
            [{"user_id": user_id, "role_id": role_id} for role_id in role_ids]
        )
        # Conflict target is the unique constraint on the pair, not the
        # surrogate primary key.
        statement = statement.on_conflict_do_nothing(
            constraint="uq_user_roles_user_role"
        )

        result = await self.session.execute(statement)
        await self.session.flush()
        return result.rowcount

    async def revoke_roles(
        self, user_id: uuid.UUID, role_ids: Sequence[uuid.UUID]
    ) -> int:
        if not role_ids:
            return 0

        result = await self.session.execute(
            delete(user_roles).where(
                user_roles.c.user_id == user_id,
                user_roles.c.role_id.in_(role_ids),
            )
        )
        await self.session.flush()
        return result.rowcount

    async def revoke_all_roles(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            delete(user_roles).where(user_roles.c.user_id == user_id)
        )
        await self.session.flush()
        return result.rowcount

    # -- Identities -----------------------------------------------------

    async def get_by_provider(
        self, provider: str, provider_user_id: str
    ) -> User | None:
        """Find the user behind a Google or Facebook account."""
        statement = (
            select(User)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .where(
                UserIdentity.provider == provider,
                UserIdentity.provider_user_id == provider_user_id,
            )
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_identity(
        self, user_id: uuid.UUID, provider: str
    ) -> UserIdentity | None:
        result = await self.session.execute(
            select(UserIdentity).where(
                UserIdentity.user_id == user_id, UserIdentity.provider == provider
            )
        )
        return result.scalar_one_or_none()

    async def add_identity(
        self,
        user_id: uuid.UUID,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
    ) -> UserIdentity:
        """Link a provider account, keeping the mirrored columns in step."""
        identity = UserIdentity(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        )
        self.session.add(identity)
        await self.session.flush()

        await self._sync_social_columns(user_id)
        return identity

    async def remove_identity(self, user_id: uuid.UUID, provider: str) -> int:
        result = await self.session.execute(
            delete(UserIdentity).where(
                UserIdentity.user_id == user_id, UserIdentity.provider == provider
            )
        )
        await self.session.flush()

        await self._sync_social_columns(user_id)
        return result.rowcount

    async def _sync_social_columns(self, user_id: uuid.UUID) -> None:
        """Rebuild `google_id`, `facebook_id` and friends from the identities.

        Recomputed from the identity rows rather than patched incrementally:
        the two can then never disagree, whatever order links and unlinks
        arrive in. This is the only place those columns are written.
        """
        result = await self.session.execute(
            select(UserIdentity)
            .where(UserIdentity.user_id == user_id)
            .order_by(UserIdentity.created_at)
        )
        identities = list(result.scalars().all())

        values: dict[str, object] = dict.fromkeys(PROVIDER_ID_COLUMNS.values(), None)
        for identity in identities:
            column = PROVIDER_ID_COLUMNS.get(identity.provider)
            if column:
                values[column] = identity.provider_user_id

        # The oldest link is the one the account arrived through.
        values["social_provider"] = identities[0].provider if identities else None
        values["is_social_login"] = bool(identities)

        await self.session.execute(
            update(User).where(User.id == user_id).values(**values)
        )
        await self.session.flush()

        # The bulk UPDATE bypasses the identity map, so a `User` already loaded
        # in this session would still show the old values.
        loaded = await self.session.get(User, user_id)
        if loaded is not None:
            await self.session.refresh(loaded)
