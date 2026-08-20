"""Business logic for extended user details."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.users.models.user_details import UserDetails
from app.modules.users.repositories.user import UserRepository
from app.modules.users.repositories.user_details import UserDetailsRepository
from app.modules.users.schemas.user_details import (
    UserDetailsCreate,
    UserDetailsUpdate,
)
from app.shared.services.activity_log_service import ActivityLogService, snapshot


class UserDetailsService:
    """Coordinates the one-to-one user details resource."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserDetailsRepository(session)
        self.users = UserRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.USERS)

    async def get(self, user_id: uuid.UUID) -> UserDetails:
        await self.users.get_or_raise(user_id)
        details = await self.repository.get_by_user_id(user_id)
        if details is None:
            raise NotFoundException("User details")
        return details

    async def create(
        self, user_id: uuid.UUID, payload: UserDetailsCreate
    ) -> UserDetails:
        user = await self.users.get_or_raise(user_id)
        if await self.repository.get_by_user_id(user_id) is not None:
            raise ConflictException("User details already exist for this user.")

        details = await self.repository.create(
            user_id=user_id, **payload.model_dump()
        )
        await self.activity.record(
            ActivityAction.CREATE,
            entity=details,
            description=f"Created details for user {user.full_name}",
            new_values=snapshot(details),
        )
        await self.session.commit()
        return details

    async def update(
        self, user_id: uuid.UUID, payload: UserDetailsUpdate
    ) -> UserDetails:
        details = await self.get(user_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return details

        before = snapshot(details, fields=changes.keys())
        updated = await self.repository.update(details, **changes)
        after = snapshot(updated, fields=changes.keys())
        if before != after:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated details for user {user_id}",
                old_values=before,
                new_values=after,
            )
        await self.session.commit()
        return updated

    async def delete(self, user_id: uuid.UUID) -> None:
        details = await self.get(user_id)
        before = snapshot(details)
        await self.repository.delete(details)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=details,
            description=f"Deleted details for user {user_id}",
            old_values=before,
        )
        await self.session.commit()
