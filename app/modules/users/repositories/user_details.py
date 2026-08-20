"""Data access for extended user details."""

import uuid

from app.modules.users.models.user_details import UserDetails
from app.shared.repositories.base import BaseRepository


class UserDetailsRepository(BaseRepository[UserDetails]):
    model = UserDetails

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserDetails | None:
        return await self.get_by_field("user_id", user_id)
