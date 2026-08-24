"""Authorization for the inquiries module.

Only the administrative half is guarded. The submission endpoint is public by
design - a visitor who has not signed in is exactly who it is for - and so it
carries a rate limit instead of a permission.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class InquiryPermission(StrEnum):
    VIEW = "inquiry.view"
    UPDATE = "inquiry.update"
    DELETE = "inquiry.delete"
    EXPORT = "inquiry.export"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(InquiryPermission.VIEW))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(InquiryPermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(InquiryPermission.DELETE))


def can_export() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(InquiryPermission.EXPORT))
