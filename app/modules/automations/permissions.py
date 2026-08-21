"""Authorization for the automations module."""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class AutomationPermission(StrEnum):
    VIEW = "automation.view"
    CREATE = "automation.create"
    UPDATE = "automation.update"
    DELETE = "automation.delete"
    PUBLISH = "automation.publish"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(AutomationPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(AutomationPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(AutomationPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(AutomationPermission.DELETE))


def can_publish() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(AutomationPermission.PUBLISH))
