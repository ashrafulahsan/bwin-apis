"""Authorization for the activity log.

Two codes, and no `activity_log.create`, `.update` or `.delete` anywhere:
entries are written by the platform, never by a caller, and nothing may edit
or remove one. A permission that does not exist cannot be granted by mistake.

`view` is the ordinary read. `export` is separated from it because pulling
the whole trail out of the system is a different act from looking something
up in it - it is the operation an outgoing administrator would use, and the
one most worth being able to grant narrowly.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class ActivityLogPermission(StrEnum):
    """Permission codes for the activity log, seeded by migration."""

    VIEW = "activity_log.view"
    EXPORT = "activity_log.export"


def can_view() -> Depends:  # type: ignore[valid-type]
    """Read the audit trail."""
    return Depends(require_permission(ActivityLogPermission.VIEW))


def can_export() -> Depends:  # type: ignore[valid-type]
    """Take the audit trail out of the system in bulk."""
    return Depends(require_permission(ActivityLogPermission.EXPORT))
