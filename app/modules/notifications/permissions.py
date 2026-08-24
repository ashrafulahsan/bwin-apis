"""Authorization for the notifications module.

Only the administrative half is guarded by permissions. The user-facing
routes are scoped instead: they are reachable by any signed-in account and
return that account's own recipient rows and nothing else, which is a rule a
permission cannot express.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class NotificationPermission(StrEnum):
    VIEW = "notification.view"
    CREATE = "notification.create"
    UPDATE = "notification.update"
    DELETE = "notification.delete"
    #: Predates this module and is still what marks an account as able to
    #: reach other people; kept so existing grants keep meaning something.
    SEND = "notification.send"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(NotificationPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(NotificationPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(NotificationPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(NotificationPermission.DELETE))
