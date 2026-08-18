"""Authorization for the menus module.

Guards name permissions rather than roles, which is the project default and
the right way round here. A navigation is content: who arranges it is a
question about what an account does, not about who it is, so an administrator
can hand `menu.update` to whoever maintains the site's navigation without
making them an admin.

This is deliberately not the categories arrangement. The *vocabulary* of menu
categories is structural and stays restricted to Super Admin and Admin; the
items filed under it are edited far more often and by more people.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class MenuPermission(StrEnum):
    """Permission codes for menu items, seeded by migration."""

    VIEW = "menu.view"
    CREATE = "menu.create"
    UPDATE = "menu.update"
    DELETE = "menu.delete"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MenuPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MenuPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    """Edit an item, re-parent it, or change its position."""
    return Depends(require_permission(MenuPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(MenuPermission.DELETE))
