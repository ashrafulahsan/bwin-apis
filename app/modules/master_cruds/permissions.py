"""Authorization for the master CRUD module.

Two resources rather than one, because the module holds two jobs that belong
to different people. `master_crud_field.*` designs the form - it changes what
every record in a category means, and a careless edit invalidates data already
stored. `master_crud.*` fills the form in, which is ordinary content work.

Giving them separate codes is what lets an administrator hand out record
editing without also handing out the schema. Guards name permissions rather
than roles, as everywhere else outside the categories module.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class MasterCrudPermission(StrEnum):
    """Permission codes for records, seeded by migration."""

    VIEW = "master_crud.view"
    CREATE = "master_crud.create"
    UPDATE = "master_crud.update"
    DELETE = "master_crud.delete"


class MasterCrudFieldPermission(StrEnum):
    """Permission codes for field definitions, seeded by migration."""

    VIEW = "master_crud_field.view"
    CREATE = "master_crud_field.create"
    UPDATE = "master_crud_field.update"
    DELETE = "master_crud_field.delete"


# -- Records ------------------------------------------------------------


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudPermission.DELETE))


# -- Field definitions --------------------------------------------------


def can_view_fields() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudFieldPermission.VIEW))


def can_create_fields() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudFieldPermission.CREATE))


def can_update_fields() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MasterCrudFieldPermission.UPDATE))


def can_delete_fields() -> Depends:  # type: ignore[valid-type]
    """Retire a field definition, or restore one."""
    return Depends(require_permission(MasterCrudFieldPermission.DELETE))
