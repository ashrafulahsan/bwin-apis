"""Business logic for roles."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.modules.roles.constants import SYSTEM_ROLES, SystemRole
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.schemas.role import RoleCreate, RoleUpdate
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)
from app.shared.utils.slug import generate_unique_slug

logger = logging.getLogger(__name__)


class RoleService:
    """Coordinates role reads and writes.

    Owns the transaction: every method that writes commits before returning.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RoleRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.ROLES)

    # -- Reads ----------------------------------------------------------

    async def get(self, role_id: uuid.UUID) -> Role:
        return await self.repository.get_or_raise(role_id)

    async def get_by_slug(self, slug: str) -> Role:
        role = await self.repository.get_by_slug(slug)
        if role is None:
            raise NotFoundException(f"Role '{slug}'")
        return role

    async def list_roles(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        is_system: bool | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Role], int]:
        filters = []
        if is_system is not None:
            filters.append(Filter.eq("is_system", is_system))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=["name", "slug", "description"],
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_all(self) -> list[Role]:
        return await self.repository.list_all()

    # -- Writes ---------------------------------------------------------

    async def create(self, payload: RoleCreate) -> Role:
        existing = await self.repository.get_by_name(payload.name, include_deleted=True)

        if existing is not None:
            # A soft-deleted role still holds its name at the database level,
            # but an administrator cannot see it in any listing - so say so
            # rather than reporting a conflict with something invisible.
            if existing.deleted_at is not None:
                raise ConflictException(
                    f"A deleted role named '{payload.name}' still holds that name. "
                    "Restore it, or rename it before reusing the name."
                )
            raise ConflictException(f"A role named '{payload.name}' already exists.")

        slug = await generate_unique_slug(payload.name, self.repository.slug_exists)

        role = await self.repository.create(
            name=payload.name,
            slug=slug,
            description=payload.description,
            level=payload.level,
            is_system=False,
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=role,
            description=f"Created role {role.name}",
            new_values=snapshot(role),
        )
        await self.session.commit()

        logger.info("Created role %s (%s)", role.name, role.slug)
        return role

    async def update(self, role_id: uuid.UUID, payload: RoleUpdate) -> Role:
        role = await self.repository.get_or_raise(role_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return role

        if (
            "name" in changes
            and changes["name"] != role.name
            and await self.repository.name_exists(changes["name"], exclude_id=role.id)
        ):
            raise ConflictException(f"A role named '{changes['name']}' already exists.")

        if role.is_system and "level" in changes and changes["level"] != role.level:
            # Authorization compares levels, so moving a built-in role could
            # silently grant a Student more power than an Admin.
            raise ForbiddenException(
                f"The level of the system role '{role.name}' cannot be changed."
            )

        before = snapshot(role, fields=changes.keys())
        updated = await self.repository.update(role, **changes)
        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=(
                    f"Updated {', '.join(sorted(new_values))} on role {updated.name}"
                ),
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    async def delete(self, role_id: uuid.UUID) -> None:
        """Soft delete a role.

        System roles are refused: deleting Super Admin would lock every
        administrator out of the platform with no way back in.
        """
        role = await self.repository.get_or_raise(role_id)

        if role.is_system:
            raise ForbiddenException(
                f"'{role.name}' is a system role and cannot be deleted."
            )

        before = snapshot(role)
        await self.repository.soft_delete(role)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=role,
            description=f"Deleted role {role.name}",
            old_values=before,
        )
        await self.session.commit()

        logger.info("Deleted role %s", role.slug)

    async def restore(self, role_id: uuid.UUID) -> Role:
        role = await self.repository.get_or_raise(role_id, include_deleted=True)
        restored = await self.repository.restore(role)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored role {restored.name}",
            new_values=snapshot(restored),
        )
        await self.session.commit()
        return restored

    # -- Seeding --------------------------------------------------------

    async def seed_system_roles(self) -> int:
        """Create any missing built-in roles.

        Idempotent, so it is safe to call on every boot. Existing roles are
        left alone rather than reset, since administrators may have renamed
        them.
        """
        created = 0

        for definition in SYSTEM_ROLES:
            if await self.repository.get_by_slug(definition["slug"]) is not None:
                continue

            await self.repository.create(
                name=definition["name"],
                slug=definition["slug"],
                description=definition["description"],
                level=definition["level"],
                is_system=True,
            )
            created += 1

        if created:
            await self.activity.record(
                ActivityAction.CREATE,
                entity_type="Role",
                description=f"Seeded {created} system role(s)",
                new_values={"created": created},
                module=ActivityModule.SYSTEM,
            )
            await self.session.commit()
            logger.info("Seeded %d system roles", created)

        return created


__all__ = ["RoleService", "SystemRole"]
