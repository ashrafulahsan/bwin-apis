"""Business logic for permissions and role grants."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
)
from app.modules.permissions.constants import (
    ALL_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
    SYSTEM_PERMISSIONS,
    build_code,
    build_label,
    split_code,
)
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.repositories.permission import PermissionRepository
from app.modules.permissions.schemas.permission import (
    PermissionCreate,
    PermissionUpdate,
)
from app.modules.roles.repositories.role import RoleRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination

logger = logging.getLogger(__name__)


class PermissionService:
    """Coordinates permission definitions and the grants that use them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PermissionRepository(session)
        self.roles = RoleRepository(session)

    # -- Reads ----------------------------------------------------------

    async def get(self, permission_id: uuid.UUID) -> Permission:
        return await self.repository.get_or_raise(permission_id)

    async def list_permissions(
        self,
        pagination: SupportsPagination,
        *,
        resource: str | None = None,
        action: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.ASC,
    ) -> tuple[list[Permission], int]:
        filters = []
        if resource:
            filters.append(Filter.eq("resource", resource))
        if action:
            filters.append(Filter.eq("action", action))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["code", "name", "description"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def grouped_by_resource(self) -> dict[str, list[Permission]]:
        """Every permission, grouped for a resource-by-action grid.

        Ascending explicitly: the repository defaults to descending, which
        would render the grid backwards.
        """
        grouped: dict[str, list[Permission]] = {}

        permissions = await self.repository.list(
            sort_by="code", sort_order=SortOrder.ASC
        )
        for permission in permissions:
            grouped.setdefault(permission.resource, []).append(permission)

        return grouped

    async def list_resources(self) -> list[str]:
        return await self.repository.resources()

    # -- Writes ---------------------------------------------------------

    async def create(self, payload: PermissionCreate) -> Permission:
        if await self.repository.code_exists(payload.code):
            raise ConflictException(f"Permission '{payload.code}' already exists.")

        resource, action = split_code(payload.code)

        permission = await self.repository.create(
            code=payload.code,
            resource=resource,
            action=action,
            name=payload.name or build_label(resource, action),
            description=payload.description,
            is_system=False,
        )
        await self.session.commit()
        return permission

    async def update(
        self, permission_id: uuid.UUID, payload: PermissionUpdate
    ) -> Permission:
        permission = await self.repository.get_or_raise(permission_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return permission

        updated = await self.repository.update(permission, **changes)
        await self.session.commit()
        return updated

    async def delete(self, permission_id: uuid.UUID) -> None:
        """Delete a permission definition.

        System permissions are refused, and so is any permission still granted
        to a role - removing it would silently strip access rather than making
        the administrator revoke it deliberately.
        """
        permission = await self.repository.get_or_raise(permission_id)

        if permission.is_system:
            raise ForbiddenException(
                f"'{permission.code}' is a system permission and cannot be deleted."
            )

        holders = await self.repository.count_roles_holding(permission.id)
        if holders:
            raise ConflictException(
                f"'{permission.code}' is still granted to {holders} role(s). "
                "Revoke it from them first."
            )

        await self.repository.delete(permission)
        await self.session.commit()

    # -- Role grants ----------------------------------------------------

    async def permissions_for_role(self, role_id: uuid.UUID) -> list[Permission]:
        await self.roles.get_or_raise(role_id)
        return await self.repository.permissions_for_role(role_id)

    async def role_has_permission(self, role_id: uuid.UUID, code: str) -> bool:
        await self.roles.get_or_raise(role_id)
        return await self.repository.role_has_permission(role_id, code)

    async def grant(self, role_id: uuid.UUID, codes: list[str]) -> list[Permission]:
        """Add permissions to a role, leaving existing grants in place."""
        role = await self.roles.get_or_raise(role_id)
        permissions = await self._resolve(codes)

        await self.repository.grant(role.id, [p.id for p in permissions])
        await self.session.commit()

        logger.info("Granted %d permissions to %s", len(permissions), role.slug)
        return await self.repository.permissions_for_role(role.id)

    async def revoke(self, role_id: uuid.UUID, codes: list[str]) -> list[Permission]:
        role = await self.roles.get_or_raise(role_id)
        permissions = await self._resolve(codes)

        await self.repository.revoke(role.id, [p.id for p in permissions])
        await self.session.commit()

        return await self.repository.permissions_for_role(role.id)

    async def replace(self, role_id: uuid.UUID, codes: list[str]) -> list[Permission]:
        """Set a role's permissions to exactly `codes`.

        This is what an admin screen submits: the full state of the checkbox
        grid, rather than a diff the client had to compute.
        """
        role = await self.roles.get_or_raise(role_id)
        permissions = await self._resolve(codes)

        await self.repository.revoke_all(role.id)
        await self.repository.grant(role.id, [p.id for p in permissions])
        await self.session.commit()

        logger.info("Replaced permissions for %s with %d", role.slug, len(permissions))
        return await self.repository.permissions_for_role(role.id)

    async def _resolve(self, codes: list[str]) -> list[Permission]:
        """Look up permissions by code, rejecting any that do not exist.

        Silently skipping unknown codes would leave an administrator believing
        they had granted access that was never granted.
        """
        permissions = await self.repository.get_by_codes(codes)

        missing = set(codes) - {permission.code for permission in permissions}
        if missing:
            raise BadRequestException(
                f"Unknown permission code(s): {', '.join(sorted(missing))}."
            )

        return permissions

    # -- Seeding --------------------------------------------------------

    async def seed_system_permissions(self) -> int:
        """Create any missing built-in permissions. Idempotent."""
        created = 0

        for resource, actions in SYSTEM_PERMISSIONS.items():
            for action in actions:
                code = build_code(resource, action)
                if await self.repository.code_exists(code):
                    continue

                await self.repository.create(
                    code=code,
                    resource=resource,
                    action=action,
                    name=build_label(resource, action),
                    is_system=True,
                )
                created += 1

        if created:
            await self.session.commit()
            logger.info("Seeded %d system permissions", created)

        return created

    async def seed_default_role_permissions(self) -> dict[str, int]:
        """Apply the default grant matrix to the seeded roles.

        Only fills in roles that hold no permissions yet, so an administrator's
        customisation survives the next deploy.
        """
        applied: dict[str, int] = {}

        for slug, codes in DEFAULT_ROLE_PERMISSIONS.items():
            role = await self.roles.get_by_slug(slug)
            if role is None:
                continue

            if await self.repository.codes_for_role(role.id):
                continue

            resolved = (
                await self.repository.list(sort_by="code")
                if codes == ALL_PERMISSIONS
                else await self.repository.get_by_codes(list(codes))
            )

            await self.repository.grant(role.id, [p.id for p in resolved])
            applied[slug] = len(resolved)

        if applied:
            await self.session.commit()

        return applied
