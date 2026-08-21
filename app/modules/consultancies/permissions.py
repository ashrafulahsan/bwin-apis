"""Authorization for the consultancies module."""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class ConsultancyPermission(StrEnum):
    VIEW = "consultancy.view"
    CREATE = "consultancy.create"
    UPDATE = "consultancy.update"
    DELETE = "consultancy.delete"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(ConsultancyPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(ConsultancyPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(ConsultancyPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(ConsultancyPermission.DELETE))
