"""Authorization for the blogs module.

Guards name permissions rather than roles, which is the project default and
the right way round here: "may this account publish" is a question about what
someone does, not about who they are. An administrator can hand `blog.publish`
to a guest columnist without making them an admin.

Publishing is a permission of its own for the reason the Editor role exists at
all - an editor writes and revises but does not decide what goes live. That
separation only means anything if the transition is guarded separately from
the edit, which is why `POST /blogs/{id}/publish` exists instead of a
`status` field on the update payload.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class BlogPermission(StrEnum):
    """Permission codes for blog posts, seeded by migration."""

    VIEW = "blog.view"
    CREATE = "blog.create"
    UPDATE = "blog.update"
    DELETE = "blog.delete"
    PUBLISH = "blog.publish"


def can_view() -> Depends:  # type: ignore[valid-type]
    """Read any post, draft ones included."""
    return Depends(require_permission(BlogPermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(BlogPermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(BlogPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(BlogPermission.DELETE))


def can_publish() -> Depends:  # type: ignore[valid-type]
    """Take a post live, pull it back to draft, or archive it."""
    return Depends(require_permission(BlogPermission.PUBLISH))
