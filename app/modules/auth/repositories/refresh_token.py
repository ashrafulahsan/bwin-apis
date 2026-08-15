"""Data access for refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update

from app.modules.auth.constants import RevocationReason
from app.modules.auth.models.refresh_token import RefreshToken
from app.shared.repositories.base import BaseRepository
from app.shared.utils.dates import utc_now


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken
    default_sort_by = "created_at"

    async def get_by_fingerprint(self, fingerprint: str) -> RefreshToken | None:
        """Find a session by the digest of its token.

        Returns revoked and expired rows too - the service needs to tell a
        token that was never issued from one that was and is now spent.
        """
        return await self.get_by_field("token_hash", fingerprint)

    async def issue(
        self,
        user_id: uuid.UUID,
        *,
        token_hash: str,
        token_id: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        return await self.create(
            user_id=user_id,
            token_hash=token_hash,
            token_id=token_id,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, reason: RevocationReason
    ) -> int:
        """Revoke every live session a user has. Returns how many were ended.

        A bulk UPDATE rather than a loop: signing out everywhere should be one
        statement, and it must not miss a session created while it runs.
        """
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now(), revoked_reason=reason.value)
        )
        await self.session.flush()
        return result.rowcount

    async def list_for_user(
        self, user_id: uuid.UUID, *, active_only: bool = True
    ) -> list[RefreshToken]:
        """Sessions belonging to a user, newest first."""
        statement = select(RefreshToken).where(RefreshToken.user_id == user_id)

        if active_only:
            statement = statement.where(
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > utc_now(),
            )

        result = await self.session.execute(
            statement.order_by(RefreshToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def purge_expired(self, *, before: datetime | None = None) -> int:
        """Delete rows that can no longer authorize anything.

        Sessions are kept after they end so they can be audited, but a row
        whose token expired long ago proves nothing and only costs space. Meant
        for a scheduled job rather than the request path.
        """
        cutoff = before or utc_now()

        result = await self.session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        )
        await self.session.flush()
        return result.rowcount
