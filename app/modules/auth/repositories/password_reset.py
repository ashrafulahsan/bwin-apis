"""Data access for password reset tokens."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update

from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.shared.repositories.base import BaseRepository
from app.shared.utils.dates import utc_now


class PasswordResetRepository(BaseRepository[PasswordResetToken]):
    model = PasswordResetToken
    default_sort_by = "created_at"

    async def get_by_fingerprint(self, fingerprint: str) -> PasswordResetToken | None:
        """Find a link by the digest of its token.

        Returns spent and expired rows too, so the service can tell a token
        that was never issued from one that has already been used.
        """
        return await self.get_by_field("token_hash", fingerprint)

    async def issue(
        self,
        user_id: uuid.UUID,
        *,
        token_hash: str,
        expires_at: datetime,
        requested_via: str | None = None,
        requested_ip: str | None = None,
    ) -> PasswordResetToken:
        return await self.create(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            requested_via=requested_via,
            requested_ip=requested_ip,
        )

    async def invalidate_outstanding(self, user_id: uuid.UUID) -> int:
        """Retire every unused link for a user.

        Asking for a new link must retire the old ones, or an attacker who
        triggered a reset earlier keeps a working token even after the real
        owner has been through the flow.
        """
        result = await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=utc_now())
        )
        await self.session.flush()
        return result.rowcount

    async def issued_since(self, user_id: uuid.UUID, since: datetime) -> int:
        """How many links this account has been sent recently."""
        result = await self.session.execute(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.created_at >= since,
            )
        )
        return int(result.scalar_one())

    async def latest_for_user(self, user_id: uuid.UUID) -> PasswordResetToken | None:
        result = await self.session.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id)
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def purge_expired(self, *, older_than: timedelta | None = None) -> int:
        """Delete links that can no longer reset anything.

        Rows are kept a while after expiry so "was a reset requested?" can be
        answered, but not forever. Meant for a scheduled job.
        """
        cutoff = utc_now() - (older_than or timedelta(days=30))

        result = await self.session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff)
        )
        await self.session.flush()
        return result.rowcount
