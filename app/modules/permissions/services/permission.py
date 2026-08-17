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
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
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
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)

logger = logging.getLogger(__name__)


class PermissionService:
    """Coordinates permission definitions and the grants that use them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PermissionRepository(session)
        self.roles = RoleRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.PERMISSIONS)

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

        await self.activity.record(
            ActivityAction.CREATE,
            entity=permission,
            description=f"Created permission {permission.code}",
            new_values=snapshot(permission),
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

        before = snapshot(permission, fields=changes.keys())
        updated = await self.repository.update(permission, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated permission {updated.code}",
                old_values=old_values,
                new_values=new_values,
            )

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

        before = snapshot(permission)
        await self.repository.delete(permission)

        await self.activity.record(
            ActivityAction.DELETE,
            entity_type="Permission",
            entity_id=before.get("code"),
            description=f"Deleted permission {permission.code}",
            old_values=before,
        )
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

        held = await self._codes_held(role.id)
        await self.repository.grant(role.id, [p.id for p in permissions])

        await self._record_grant_change(
            ActivityAction.PERMISSION_GRANT,
            role,
            held,
            f"Granted {len(permissions)} permission(s) to {role.name}",
        )
        await self.session.commit()

        logger.info("Granted %d permissions to %s", len(permissions), role.slug)
        return await self.repository.permissions_for_role(role.id)

    async def revoke(self, role_id: uuid.UUID, codes: list[str]) -> list[Permission]:
        role = await self.roles.get_or_raise(role_id)
        permissions = await self._resolve(codes)

        held = await self._codes_held(role.id)
        await self.repository.revoke(role.id, [p.id for p in permissions])

        await self._record_grant_change(
            ActivityAction.PERMISSION_REVOKE,
            role,
            held,
            f"Revoked {len(permissions)} permission(s) from {role.name}",
        )
        await self.session.commit()

        return await self.repository.permissions_for_role(role.id)

    async def replace(self, role_id: uuid.UUID, codes: list[str]) -> list[Permission]:
        """Set a role's permissions to exactly `codes`.

        This is what an admin screen submits: the full state of the checkbox
        grid, rather than a diff the client had to compute.
        """
        role = await self.roles.get_or_raise(role_id)
        permissions = await self._resolve(codes)

        held = await self._codes_held(role.id)

        await self.repository.revoke_all(role.id)
        await self.repository.grant(role.id, [p.id for p in permissions])

        await self._record_grant_change(
            ActivityAction.PERMISSION_GRANT,
            role,
            held,
            f"Replaced the permissions of {role.name} with {len(permissions)}",
        )
        await self.session.commit()

        logger.info("Replaced permissions for %s with %d", role.slug, len(permissions))
        return await self.repository.permissions_for_role(role.id)

    async def _codes_held(self, role_id: uuid.UUID) -> list[str]:
        return sorted(
            permission.code
            for permission in await self.repository.permissions_for_role(role_id)
        )

    async def _record_grant_change(
        self, action: ActivityAction, role: Role, held: list[str], description: str
    ) -> None:
        """Record a change in what a role may do, as the whole set either side.

        The delta alone would not answer the question these entries exist for
        - "what could this role do on the day it happened" - and a role's
        permission set is small enough to write down in full.
        """
        now_held = await self._codes_held(role.id)

        if now_held == held:
            return

        await self.activity.record(
            action,
            entity=role,
            description=description,
            entity_type="Role",
            old_values={"permissions": held},
            new_values={"permissions": now_held},
        )

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
            await self.activity.record(
                ActivityAction.CREATE,
                entity_type="Permission",
                description=f"Seeded {created} system permission(s)",
                new_values={"created": created},
                module=ActivityModule.SYSTEM,
            )
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
            await self.activity.record(
                ActivityAction.PERMISSION_GRANT,
                entity_type="Role",
                description=(
                    "Seeded the default permissions of "
                    f"{len(applied)} role(s): {', '.join(sorted(applied))}"
                ),
                new_values={"granted": applied},
                module=ActivityModule.SYSTEM,
            )
            await self.session.commit()

        return applied
