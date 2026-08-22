"""Data access for newsletter subscriptions."""

import uuid

from sqlalchemy import func, select

from app.modules.subscriptions.models.subscription import Subscription
from app.shared.repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get_by_email(
        self, email: str, *, include_deleted: bool = False
    ) -> Subscription | None:
        """Find an address.

        `include_deleted` matters more here than elsewhere: `email` is unique
        across the whole table, so a soft-deleted row still occupies the
        address. Signing up again has to find that row and revive it, or the
        insert fails on a constraint the caller cannot see.
        """
        return await self.get_by_field("email", email, include_deleted=include_deleted)

    async def email_exists(
        self, email: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        """Whether the address is taken, deleted rows included."""
        conditions = [Subscription.email == email]
        if exclude_id is not None:
            conditions.append(Subscription.id != exclude_id)
        result = await self.session.execute(
            select(select(Subscription.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def get_by_confirmation_token(self, token_hash: str) -> Subscription | None:
        return await self.get_by_field("confirmation_token_hash", token_hash)

    async def count_by_status(self) -> dict[str, int]:
        """How many addresses sit in each status.

        Grouped in SQL rather than by counting a fetched list: the whole point
        is to answer "how big is the list?" without loading it.
        """
        result = await self.session.execute(
            select(Subscription.status, func.count())
            .where(Subscription.deleted_at.is_(None))
            .group_by(Subscription.status)
        )
        return {status: int(total) for status, total in result.all()}
