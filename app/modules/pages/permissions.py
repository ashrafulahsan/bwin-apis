"""Authorization for the pages module.

Guards name permissions rather than roles, which is the project default and
the right way round here: "may this account publish" is a question about what
someone does, not about who they are.

The `page.*` codes were seeded with the platform's original permission set, so
this module needs no migration of its own - it is the code that was always
meant to use them. Publishing is a permission apart for the reason the Editor
role exists at all: an editor writes and revises but does not decide what goes
live, which only means something if the transition is guarded separately from
the edit.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class PagePermission(StrEnum):
    """Permission codes for pages, seeded with the original permission set."""

    VIEW = "page.view"
    CREATE = "page.create"
    UPDATE = "page.update"
    DELETE = "page.delete"
    PUBLISH = "page.publish"


def can_view() -> Depends:  # type: ignore[valid-type]
    """Read any page, draft ones included."""
    return Depends(require_permission(PagePermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(PagePermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(PagePermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(PagePermission.DELETE))


def can_publish() -> Depends:  # type: ignore[valid-type]
    """Take a page live, pull it back to draft, or archive it."""
    return Depends(require_permission(PagePermission.PUBLISH))
