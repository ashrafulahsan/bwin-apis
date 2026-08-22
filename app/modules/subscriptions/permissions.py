"""Authorization for the subscriptions module.

A subscriber list is personal data: a set of real addresses belonging to real
people. The grants are deliberately narrower than a content module's - the
roles that run the newsletter get it, and nobody else needs a copy of it.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class SubscriptionPermission(StrEnum):
    VIEW = "subscription.view"
    CREATE = "subscription.create"
    UPDATE = "subscription.update"
    DELETE = "subscription.delete"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SubscriptionPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SubscriptionPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SubscriptionPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SubscriptionPermission.DELETE))
