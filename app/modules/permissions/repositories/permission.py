"""Data access for permissions and role grants."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.shared.repositories.base import BaseRepository


class PermissionRepository(BaseRepository[Permission]):
    model = Permission
    default_sort_by = "code"

    async def get_by_code(self, code: str) -> Permission | None:
        return await self.get_by_field("code", code)

    async def get_by_codes(self, codes: Sequence[str]) -> list[Permission]:
        """Fetch several permissions at once, for bulk grants."""
        if not codes:
            return []

        result = await self.session.execute(
            select(Permission)
            .where(Permission.code.in_(codes))
            .order_by(Permission.code)
        )
        return list(result.scalars().all())

    async def code_exists(self, code: str) -> bool:
        result = await self.session.execute(
            select(select(Permission.id).where(Permission.code == code).exists())
        )
        return bool(result.scalar_one())

    async def resources(self) -> list[str]:
        """Distinct resources, for grouping the admin grid."""
        result = await self.session.execute(
            select(Permission.resource).distinct().order_by(Permission.resource)
        )
        return list(result.scalars().all())

    # -- Role grants ----------------------------------------------------

    async def permissions_for_role(self, role_id: uuid.UUID) -> list[Permission]:
        statement = (
            select(Permission)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_id)
            .order_by(Permission.code)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def codes_for_role(self, role_id: uuid.UUID) -> set[str]:
        statement = (
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_id)
        )
        result = await self.session.execute(statement)
        return set(result.scalars().all())

    async def role_has_permission(self, role_id: uuid.UUID, code: str) -> bool:
        statement = select(
            select(role_permissions.c.role_id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(role_permissions.c.role_id == role_id, Permission.code == code)
            .exists()
        )
        result = await self.session.execute(statement)
        return bool(result.scalar_one())

    async def grant(
        self, role_id: uuid.UUID, permission_ids: Sequence[uuid.UUID]
    ) -> int:
        """Grant permissions, ignoring any the role already holds."""
        if not permission_ids:
            return 0

        statement = pg_insert(role_permissions).values(
            [
                {"role_id": role_id, "permission_id": permission_id}
                for permission_id in permission_ids
            ]
        )
        # Re-granting is a no-op. The conflict target is the unique
        # constraint on the pair, not the surrogate primary key.
        statement = statement.on_conflict_do_nothing(
            constraint="uq_role_permissions_role_permission"
        )

        result = await self.session.execute(statement)
        await self.session.flush()
        return result.rowcount

    async def revoke(
        self, role_id: uuid.UUID, permission_ids: Sequence[uuid.UUID]
    ) -> int:
        if not permission_ids:
            return 0

        result = await self.session.execute(
            delete(role_permissions).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id.in_(permission_ids),
            )
        )
        await self.session.flush()
        return result.rowcount

    async def revoke_all(self, role_id: uuid.UUID) -> int:
        result = await self.session.execute(
            delete(role_permissions).where(role_permissions.c.role_id == role_id)
        )
        await self.session.flush()
        return result.rowcount

    async def count_roles_holding(self, permission_id: uuid.UUID) -> int:
        """How many roles grant this permission, checked before deleting it."""
        result = await self.session.execute(
            select(func.count())
            .select_from(role_permissions)
            .where(role_permissions.c.permission_id == permission_id)
        )
        return int(result.scalar_one())
